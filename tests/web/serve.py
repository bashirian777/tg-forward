"""Serve only frontend assets on an ephemeral local port for browser checks."""
import asyncio
import signal
from aiohttp import web
from src.web_server import WebServer


async def main():
    server = WebServer(None, None)
    app = web.Application()
    app.router.add_get("/", server.handle_index)
    app.router.add_get("/static/{name:.*}", server.handle_static)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    print(f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}", flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
