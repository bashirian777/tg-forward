"""Serve built Vue assets only; browser tests intercept every API request."""
import os
from pathlib import Path
from werkzeug.serving import make_server
from tg_forwarder.web.app import create_app

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    app = create_app(None, root / "frontend/dist")
    server = make_server("127.0.0.1", int(os.environ.get("UI_TEST_PORT", "18082")), app, threaded=True)
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
