"""Single-process HTTP serving with a separately owned asyncio runtime."""
import signal
from waitress import create_server

from tg_forwarder.web.app import create_app
from .bridge import RuntimeBridge
from .service import ForwarderService


def serve(startup, manager, tracker):
    runtime = RuntimeBridge(lambda: ForwarderService(startup, manager, tracker)).start()
    server = None
    previous = {}
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    try:
        app = create_app(runtime)
        proxy = {"trusted_proxy": startup.web_trusted_proxy, "trusted_proxy_count": 1,
            "trusted_proxy_headers": {"x-forwarded-proto", "x-forwarded-for"}} if startup.web_trusted_proxy else {}
        server = create_server(app, host=startup.web_host, port=startup.web_port, threads=4, **proxy)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, interrupt)
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.close()
        try:
            runtime.stop()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
