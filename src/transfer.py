"""Bounded parallel Telegram transfers with verified block manifests."""
import asyncio
import hashlib
import inspect
import json
import math
import os
import secrets
import time
from pathlib import Path
from telethon import functions, types
from telethon.errors import FloodWaitError, FileReferenceExpiredError, FilerefUpgradeNeededError
from .workspace import atomic_json

PART_SIZE = 512 * 1024  # Telethon's maximum download request and Telegram upload part.


async def run_workers(items, workers, operation):
    iterator = iter(items)
    async def worker():
        for item in iterator:
            await operation(item)
    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def retry(operation):
    for attempt in range(3):
        try:
            return await operation()
        except (FloodWaitError, FileReferenceExpiredError, FilerefUpgradeNeededError):
            raise
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            await asyncio.sleep(0.25 * 2 ** attempt)


async def report(callback, current, total):
    if callback:
        result = callback(current, total)
        if inspect.isawaitable(result):
            await result


def load_manifest(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


class ParallelTransfer:
    def __init__(self, client, download_workers=4, upload_workers=4):
        self.client = client
        self.download_workers = download_workers
        self.upload_workers = upload_workers

    async def download(self, message, destination, progress=None):
        document = message.media.document
        size = document.size
        identity = [document.id, size, document.dc_id]
        destination = Path(destination)
        partial = Path(str(destination) + ".part")
        manifest_path = Path(str(destination) + ".download.json")
        state = load_manifest(manifest_path)
        if state.get("identity") != identity or state.get("part_size") != PART_SIZE:
            state = {"identity": identity, "part_size": PART_SIZE, "blocks": {}}
            partial.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
        # Completed files are accepted only after verifying all recorded blocks.
        if destination.exists() and not partial.exists():
            os.replace(destination, partial)
        fd = os.open(partial, os.O_RDWR | os.O_CREAT, 0o600)
        count = math.ceil(size / PART_SIZE)
        valid = {}
        for key, digest in state.get("blocks", {}).items():
            try:
                index = int(key)
                if not 0 <= index < count:
                    continue
                expected = min(PART_SIZE, size - index * PART_SIZE)
                data = os.pread(fd, expected, index * PART_SIZE)
                if len(data) == expected and hashlib.sha256(data).hexdigest() == digest:
                    valid[str(index)] = digest
            except (ValueError, TypeError):
                continue
        state["blocks"] = valid
        current = sum(min(PART_SIZE, size - int(i) * PART_SIZE) for i in valid)
        last_save = time.monotonic()
        async def fetch(index):
            nonlocal current, last_save
            expected = min(PART_SIZE, size - index * PART_SIZE)
            async def request():
                stream = self.client.iter_download(message, offset=index * PART_SIZE,
                    request_size=PART_SIZE, chunk_size=PART_SIZE, limit=1, file_size=size, dc_id=document.dc_id)
                try:
                    data = bytes(await stream.__anext__())
                    if len(data) != expected:
                        raise OSError(f"Incomplete block {index}: {len(data)} instead of {expected}")
                    return data
                finally:
                    await stream.close()
            data = await retry(request)
            if os.pwrite(fd, data, index * PART_SIZE) != len(data):
                raise OSError("Short disk write")
            state["blocks"][str(index)] = hashlib.sha256(data).hexdigest()
            current += len(data)
            if time.monotonic() - last_save >= 1:
                os.fsync(fd)
                atomic_json(manifest_path, state)
                last_save = time.monotonic()
            await report(progress, current, size)
        try:
            await report(progress, current, size)
            await run_workers((i for i in range(count) if str(i) not in valid), min(self.download_workers, max(1, count)), fetch)
            if len(state["blocks"]) != count or current != size:
                raise OSError("Downloaded file has missing blocks")
            if os.fstat(fd).st_size != size:
                os.ftruncate(fd, size)
            os.fsync(fd)
            atomic_json(manifest_path, state)
        finally:
            os.fsync(fd)
            os.close(fd)
            atomic_json(manifest_path, state)
        os.replace(partial, destination)
        return str(destination)

    async def upload(self, source, progress=None):
        source = Path(source)
        size = source.stat().st_size
        identity = [size, source.stat().st_mtime_ns]
        manifest = Path(str(source) + ".upload.json")
        state = load_manifest(manifest)
        if state.get("identity") != identity or time.time() - state.get("created_at", 0) > 3600:
            state = {"identity": identity, "file_id": secrets.randbits(63), "created_at": time.time(), "parts": []}
        completed = {i for i in state.get("parts", []) if type(i) is int and 0 <= i < math.ceil(size / PART_SIZE)}
        count = math.ceil(size / PART_SIZE)
        if not count:
            raise ValueError("Cannot upload an empty file")
        big = size > 10 * 1024 * 1024
        fd = os.open(source, os.O_RDONLY)
        current = sum(min(PART_SIZE, size - i * PART_SIZE) for i in completed)
        last_save = time.monotonic()
        async def send(index):
            nonlocal current, last_save
            data = os.pread(fd, PART_SIZE, index * PART_SIZE)
            if len(data) != min(PART_SIZE, size - index * PART_SIZE):
                raise OSError("Source changed during upload")
            request = functions.upload.SaveBigFilePartRequest(state["file_id"], index, count, data) if big else functions.upload.SaveFilePartRequest(state["file_id"], index, data)
            async def call():
                if not await self.client(request):
                    raise OSError(f"Telegram rejected upload part {index}")
            await retry(call)
            completed.add(index)
            current += len(data)
            state["parts"] = sorted(completed)
            if time.monotonic() - last_save >= 1:
                atomic_json(manifest, state)
                last_save = time.monotonic()
            await report(progress, current, size)
        try:
            await report(progress, current, size)
            await run_workers((i for i in range(count) if i not in completed), min(self.upload_workers, count), send)
            if source.stat().st_mtime_ns != identity[1] or source.stat().st_size != size:
                raise OSError("Source changed during upload")
            if big:
                return types.InputFileBig(state["file_id"], count, source.name)
            md5 = hashlib.md5()
            for index in range(count):
                md5.update(os.pread(fd, PART_SIZE, index * PART_SIZE))
            return types.InputFile(state["file_id"], count, source.name, md5.hexdigest())
        finally:
            os.close(fd)
            state["parts"] = sorted(completed)
            atomic_json(manifest, state)
