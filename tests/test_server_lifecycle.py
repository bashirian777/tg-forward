"""Offline production HTTP smoke check, including SIGTERM and runtime teardown."""
import json
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def test_waitress_serves_assets_and_api_on_one_port_and_exits(tmp_path):
    code = '''
from dataclasses import replace
from pathlib import Path
import sys
from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.runtime import server
from tg_forwarder.runtime.service import ForwarderService
from tg_forwarder import cli
from tests.test_configuration import startup
root = Path(sys.argv[1])
cm = ConfigManager(root / "test.db", project_root=root)
cm.initialize("密码")
cm.save_app_config(replace(cm.get_config(), temp_dir=str(root / "temp")))
class Offline(ForwarderService):
    async def start_background(self):
        pass
    async def shutdown(self):
        await super().shutdown()
        print("runtime-stopped", flush=True)
server.ForwarderService = Offline
original = server.create_server
def capture(*args, **kwargs):
    instance = original(*args, **kwargs)
    print(instance.effective_port, flush=True)
    return instance
server.create_server = capture
cli.StartupConfig.load = lambda *_: replace(startup(root),
    db_path=Path(cm.db.path), session_path=root / "forwarder.session", web_port=0, web_trusted_proxy="127.0.0.1")
sys.argv = ["tg-forward", "--log-level", "ERROR", "serve"]
cli.run()
'''
    process = subprocess.Popen([sys.executable, "-u", "-c", code, str(tmp_path)], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=15), "HTTP server did not bind"
        port = int(process.stdout.readline().strip())
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/tasks", timeout=5) as response:
            assert b"/assets/" in response.read()
        request = urllib.request.Request(base + "/api/auth", data=json.dumps({"password": "密码"}).encode(),
            headers={"Content-Type": "application/json", "X-Forwarded-Proto": "https"})
        with urllib.request.urlopen(request, timeout=5) as response:
            session = json.load(response)
            cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            assert "HttpOnly" in response.headers["Set-Cookie"]
            assert "Secure" in response.headers["Set-Cookie"]
        assert session["authenticated"]
        with urllib.request.urlopen(urllib.request.Request(base + "/api/tasks", headers={"Cookie": cookie}), timeout=5) as response:
            assert json.load(response) == []
        process.send_signal(signal.SIGTERM)
        out, err = process.communicate(timeout=15)
        assert process.returncode == 0, err
        assert "runtime-stopped" in out
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
