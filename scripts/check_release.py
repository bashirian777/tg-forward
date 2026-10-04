"""Inspect and install a built wheel in an isolated working directory."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import venv
import zipfile

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "tg_forwarder/web/dist/index.html" in names, "wheel is missing the frontend"
        assert any(name.startswith("tg_forwarder/web/dist/assets/") for name in names)
        assert not any(name.startswith(("src/", "tests/", "frontend/", "data/")) for name in names)
        assert not any(Path(name).name.startswith(".env") or name.endswith((".db", ".session", ".tar.gz")) for name in names)
        metadata = archive.read(next(name for name in names if name.endswith(".dist-info/METADATA"))).decode()
        assert "Requires-Dist: Flask" in metadata and "Requires-Dist: waitress" in metadata
        assert "aiohttp" not in metadata
    with tempfile.TemporaryDirectory(prefix="tg-forward-wheel-") as directory:
        root = Path(directory)
        env = root / "venv"
        venv.EnvBuilder(with_pip=True).create(env)
        python = env / "bin/python"
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], check=True)
        subprocess.run([str(env / "bin/tg-forward"), "--help"], cwd=root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(python), "-m", "tg_forwarder", "--help"], cwd=root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(python), "-m", "pip", "check"], cwd=root, check=True)
        # No build tools, Node, project imports, Telegram connections or real data.
        code = '''
from pathlib import Path
import re
from tg_forwarder.config.paths import PROJECT_ROOT
from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.storage.passwords import verify_password
from tg_forwarder.web.app import create_app
root = Path.cwd()
assert PROJECT_ROOT == root
config = ConfigManager()
config.initialize("本地测试密码")
assert Path(config.db.path) == root / "data/forwarder.db"
assert verify_password(config.get_config().web_password, "本地测试密码")
client = create_app(None).test_client()
for path in ("/", "/tasks", "/resources", "/settings", "/activity"):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', response.get_data(as_text=True)):
        static = client.get(asset)
        assert static.status_code == 200
        assert "immutable" in static.headers["Cache-Control"]
for path in ("/assets/missing.js", "/api/missing", "/.env", "/unknown"):
    assert client.get(path).status_code == 404
print("wheel: isolated install, CLI, data paths and all SPA assets passed")
'''
        subprocess.run([str(python), "-I", "-c", code], cwd=root, check=True)


if __name__ == "__main__":
    main()
