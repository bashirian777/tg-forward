"""Telegram transfer benchmark. Requires the project's forwarder to be stopped.

Downloads an existing source message and uploads raw parts to Telegram temporary
storage. It never sends a Telegram message or finalizes media in a target chat.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import tempfile
import time

from telethon import TelegramClient
from src.transfer import ParallelTransfer


def assert_session_unused(project):
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            command = (entry / "cmdline").read_bytes().split(b"\0")
            cwd = (entry / "cwd").resolve()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if cwd == project and b"src.main" in command and any(x in command for x in (b"bot", b"start", b"login")):
            raise RuntimeError("Stop the project's Telegram process before benchmarking its session")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def benchmark(args):
    project = Path.cwd().resolve()
    assert_session_unused(project)
    if Path(args.output).exists():
        raise ValueError("Choose a new report path; existing files will not be overwritten")
    with sqlite3.connect("file:config/forwarder.db?mode=ro", uri=True) as conn:
        settings = json.loads(conn.execute("SELECT data FROM app_settings WHERE id=1").fetchone()[0])
        row = conn.execute("SELECT data FROM tasks WHERE task_id=?", (args.task_id,)).fetchone()
        if not row:
            raise ValueError("Task not found")
        task = json.loads(row[0])
    client = TelegramClient("forwarder", settings["api_id"], settings["api_hash"],
        request_retries=1, connection_retries=1, flood_sleep_threshold=0)
    results = []
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Existing session is not authorized")
        with tempfile.TemporaryDirectory(prefix="tg-forward-benchmark-", dir=args.temp_dir) as directory:
            source = Path(directory) / "baseline.bin"
            source_hash = None
            size = None
            modes = ["telethon", 1, 4, 8]
            for mode in modes:
                message = await client.get_messages(task["source_channel"], ids=args.message_id)
                if not message or not message.document:
                    raise ValueError("Choose a source document/video message")
                size = message.document.size
                if not 0 < size <= args.max_size_mb * 1024 * 1024:
                    raise ValueError("Source exceeds the configured benchmark size limit")
                if shutil.disk_usage(directory).free < 2 * size + 512 * 1024 * 1024:
                    raise ValueError("Insufficient disk space for a benchmark with reserve")
                path = source if mode == "telethon" else Path(directory) / f"worker-{mode}.bin"
                for direction in ("download", "upload"):
                    before_cpu = time.process_time()
                    started = time.monotonic()
                    record = {"mode": mode, "direction": direction, "bytes": size}
                    try:
                        if direction == "download":
                            if mode == "telethon":
                                await asyncio.wait_for(client.download_media(message, file=str(path)), args.timeout)
                                source_hash = sha256(path)
                            else:
                                await asyncio.wait_for(ParallelTransfer(client, mode, mode).download(message, path), args.timeout)
                                assert sha256(path) == source_hash, "Downloaded content differs from baseline"
                            assert path.stat().st_size == size
                        elif mode == "telethon":
                            await asyncio.wait_for(client.upload_file(str(source)), args.timeout)
                        else:
                            await asyncio.wait_for(ParallelTransfer(client, mode, mode).upload(source,
                                state_path=str(Path(directory) / f"upload-{mode}.json")), args.timeout)
                        record["ok"] = True
                    except Exception as error:
                        record.update(ok=False, error=type(error).__name__)
                    record["seconds"] = round(time.monotonic() - started, 3)
                    record["cpu_seconds"] = round(time.process_time() - before_cpu, 3)
                    record["mib_per_second"] = round(size / max(record["seconds"], 0.001) / (1024 * 1024), 3) if record["ok"] else None
                    record["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    results.append(record)
                    print(json.dumps(record), flush=True)
                    if not record["ok"]:
                        raise RuntimeError("Benchmark stopped after failure; inspect the report before retrying")
                if mode != "telethon":
                    path.unlink()
    finally:
        await client.disconnect()
        Path(args.output).write_text(json.dumps({"results": results, "scope": "raw download/upload only; no Telegram messages sent"}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--message-id", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--temp-dir", default=None)
    parser.add_argument("--max-size-mb", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=180)
    asyncio.run(benchmark(parser.parse_args()))


if __name__ == "__main__":
    main()
