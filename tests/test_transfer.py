"""Parallel transfer integrity, resume, and cancellation tests."""
import asyncio
from types import SimpleNamespace
from pathlib import Path
import pytest
from telethon import types, functions
from src.transfer import ParallelTransfer, PART_SIZE, load_manifest


class Stream:
    def __init__(self, client, offset):
        self.client, self.offset = client, offset
    async def __anext__(self):
        client = self.client
        client.active += 1
        client.peak = max(client.peak, client.active)
        try:
            await asyncio.sleep(client.latency)
            if self.offset in client.failures:
                raise RuntimeError("interrupted")
            client.downloaded.append(self.offset)
            return client.data[self.offset:self.offset + PART_SIZE]
        finally:
            client.active -= 1
    async def close(self):
        pass


class Client:
    def __init__(self, data):
        self.data = data
        self.active = self.peak = 0
        self.failures = set()
        self.downloaded = []
        self.uploaded = {}
        self.requests = []
        self.latency = 0.001
    def iter_download(self, message, **kwargs):
        return Stream(self, kwargs["offset"])
    async def __call__(self, request):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.latency)
            if request.file_part in self.failures:
                raise RuntimeError("interrupted")
            self.requests.append(request)
            self.uploaded[request.file_part] = request.bytes
            return True
        finally:
            self.active -= 1


def message(data):
    return SimpleNamespace(media=SimpleNamespace(document=SimpleNamespace(id=1, size=len(data), dc_id=2)))


@pytest.mark.asyncio
async def test_parallel_download_is_exact_and_bounded(tmp_path):
    data = bytes(range(251)) * 18000
    client = Client(data)
    out = tmp_path / "media.mp4"
    progress = []
    await ParallelTransfer(client, 4).download(message(data), out, lambda n, total: progress.append(n))
    assert out.read_bytes() == data
    assert 1 < client.peak <= 4
    assert progress == sorted(progress)
    assert progress[-1] == len(data)


@pytest.mark.asyncio
async def test_resume_verifies_blocks_and_redownloads_corruption(tmp_path):
    data = b"a" * (PART_SIZE * 3 + 11)
    client = Client(data)
    client.failures = {PART_SIZE * 2}
    transfer = ParallelTransfer(client, 1)
    out = tmp_path / "media.mp4"
    with pytest.raises(RuntimeError):
        await transfer.download(message(data), out)
    assert client.downloaded == [0, PART_SIZE]
    partial = Path(str(out) + ".part")
    with partial.open("r+b") as file:
        file.write(b"corrupt")
    client.failures.clear()
    client.downloaded.clear()
    await transfer.download(message(data), out)
    assert PART_SIZE not in client.downloaded
    assert 0 in client.downloaded
    assert out.read_bytes() == data


@pytest.mark.asyncio
async def test_upload_resume_keeps_file_id_and_missing_parts(tmp_path):
    source = tmp_path / "media.mp4"
    data = b"b" * (PART_SIZE * 3 + 13)
    source.write_bytes(data)
    client = Client(data)
    client.failures = {2}
    transfer = ParallelTransfer(client, upload_workers=1)
    with pytest.raises(RuntimeError):
        await transfer.upload(source)
    state = load_manifest(str(source) + ".upload.json")
    assert state["parts"] == [0, 1]
    client.failures.clear()
    client.requests.clear()
    uploaded = await transfer.upload(source)
    assert uploaded.id == state["file_id"]
    assert [request.file_part for request in client.requests] == [2, 3]
    assert b"".join(client.uploaded[i] for i in range(4)) == data
    assert bytes(uploaded)


@pytest.mark.asyncio
async def test_cancellation_joins_workers_before_return(tmp_path):
    data = b"x" * PART_SIZE * 8
    client = Client(data)
    client.latency = 1
    runner = asyncio.create_task(ParallelTransfer(client, 4).download(message(data), tmp_path / "file"))
    while not client.active:
        await asyncio.sleep(0)
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert client.active == 0
    assert load_manifest(str(tmp_path / "file") + ".download.json")["blocks"] == {}


@pytest.mark.asyncio
async def test_complete_download_retry_preserves_upload_identity(tmp_path):
    data = b"x" * (PART_SIZE * 2 + 15)
    client = Client(data)
    out = tmp_path / "video.mp4"
    transfer = ParallelTransfer(client, 1, 1)
    await transfer.download(message(data), out)
    modified = out.stat().st_mtime_ns
    client.failures = {1}
    with pytest.raises(RuntimeError):
        await transfer.upload(out)
    original_id = load_manifest(str(out) + ".upload.json")["file_id"]
    client.failures.clear()
    await transfer.download(message(data), out)
    assert out.stat().st_mtime_ns == modified
    assert (await transfer.upload(out)).id == original_id
