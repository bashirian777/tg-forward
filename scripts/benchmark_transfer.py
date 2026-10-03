"""Deterministic transfer comparison. This does not contact Telegram."""
import argparse
import asyncio
import json
import time
from pathlib import Path
import tempfile
from types import SimpleNamespace
from src.transfer import ParallelTransfer, PART_SIZE


class Stream:
    def __init__(self, peer, offset):
        self.peer, self.offset = peer, offset
    async def __anext__(self):
        await asyncio.sleep(self.peer.latency)
        return self.peer.data[self.offset:self.offset + PART_SIZE]
    async def close(self):
        pass


class Peer:
    def __init__(self, data, latency):
        self.data, self.latency = data, latency
    def iter_download(self, message, **kwargs):
        return Stream(self, kwargs["offset"])
    async def __call__(self, request):
        await asyncio.sleep(self.latency)
        return True


async def run(size_mb, latency_ms):
    data = bytes(range(256)) * (size_mb * 4096)
    message = SimpleNamespace(media=SimpleNamespace(document=SimpleNamespace(id=1, dc_id=2, size=len(data))))
    results = []
    with tempfile.TemporaryDirectory(prefix="tg-transfer-benchmark-") as directory:
        for workers in (1, 4, 8):
            path = Path(directory) / f"file-{workers}.mp4"
            peer = Peer(data, latency_ms / 1000)
            transfer = ParallelTransfer(peer, workers, workers)
            start = time.perf_counter()
            await transfer.download(message, path)
            download = time.perf_counter() - start
            assert path.read_bytes() == data
            start = time.perf_counter()
            await transfer.upload(path)
            upload = time.perf_counter() - start
            results.append({"workers": workers, "download_seconds": round(download, 3), "upload_seconds": round(upload, 3),
                "download_mib_s": round(size_mb / download, 2), "upload_mib_s": round(size_mb / upload, 2)})
    print(json.dumps({"kind": "simulated_latency", "size_mb": size_mb, "request_latency_ms": latency_ms, "results": results}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--size-mb", type=int, default=16)
    parser.add_argument("--latency-ms", type=float, default=20)
    args = parser.parse_args()
    asyncio.run(run(args.size_mb, args.latency_ms))
