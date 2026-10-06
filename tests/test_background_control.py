"""Exercise background controls against a real HTTP process with Telegram disabled."""
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
from types import SimpleNamespace
import urllib.request

import pytest

from tg_forwarder.config.startup import DEFAULTS
from tg_forwarder.storage.config_store import ConfigManager
from tests.support import VALUES

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(tmp_path):
    project = tmp_path / "checkout"
    project.mkdir()
    shutil.copytree(ROOT / "src", project / "src", ignore=shutil.ignore_patterns("dist", "__pycache__", "*.pyc"))
    for name in ("run.sh", "pyproject.toml"):
        shutil.copyfile(ROOT / name, project / name)
    # Keep the actual CLI and HTTP server; disable only the Telegram connection.
    offline = '''
from tg_forwarder.runtime.service import ForwarderService
async def offline_start(self):
    with Path('lifecycle.txt').open('a') as log:
        log.write('started\\n')
original_shutdown = ForwarderService.shutdown
async def offline_shutdown(self):
    await original_shutdown(self)
    with Path('lifecycle.txt').open('a') as log:
        log.write('stopped\\n')
ForwarderService.start_background = offline_start
ForwarderService.shutdown = offline_shutdown
'''
    (project / "main.py").write_text((ROOT / "main.py").read_text().replace(
        'from tg_forwarder.cli import run', offline + '\nfrom tg_forwarder.cli import run'))
    executable = project / ".venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    executable.chmod(0o755)
    environment = {key: value for key, value in os.environ.items()
        if key not in DEFAULTS and key not in {"PYTHONPATH", "VIRTUAL_ENV"}}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env_file = project / ".env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in dict(VALUES,
        WEB_HOST="127.0.0.1", WEB_PORT=str(port)).items()))
    cm = ConfigManager(project / "data/forwarder.db", project_root=project)
    cm.initialize("test-password")
    cm.save_app_config(replace(cm.get_config(), temp_dir=str(project / "temp")))
    pid_file = project / "data/run/forwarder.pid"

    def command(*arguments, expected=0):
        result = subprocess.run(["bash", str(project / "run.sh"), *arguments], cwd=tmp_path,
            env=environment, text=True, capture_output=True, timeout=40)
        assert result.returncode == expected, result.stdout + result.stderr
        return result

    def http_status():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/auth", timeout=3) as response:
            return json.load(response)

    def events():
        return (project / "lifecycle.txt").read_text().splitlines()

    try:
        yield SimpleNamespace(root=project, command=command, pid_file=pid_file,
            env_file=env_file, http_status=http_status, events=events, port=port)
    finally:
        # Fixture cleanup stays inside this checkout, including after failed assertions.
        subprocess.run(["bash", str(project / "run.sh"), "stop"], cwd=tmp_path,
            env=environment, capture_output=True, timeout=40)
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if (entry / "cwd").resolve() == project and str(project / "main.py").encode() in (entry / "cmdline").read_bytes():
                    os.kill(int(entry.name), signal.SIGKILL)
            except (OSError, RuntimeError):
                pass


def test_background_start_restart_status_and_graceful_stop(runner):
    assert "Usage:" in runner.command().stdout
    assert "Stopped." in runner.command("status").stdout
    assert not runner.pid_file.exists()
    assert "Started in background" in runner.command("start").stdout
    first = int(runner.pid_file.read_text())
    assert not runner.http_status()["authenticated"]
    assert str(first) in runner.command("status").stdout
    assert "Already running" in runner.command("start").stdout
    assert int(runner.pid_file.read_text()) == first
    assert runner.events() == ["started"]
    # An inherited control lock would make this restart fail.
    assert "Started in background" in runner.command("restart").stdout
    second = int(runner.pid_file.read_text())
    assert second != first
    assert runner.events() == ["started", "stopped", "started"]
    assert not runner.http_status()["authenticated"]
    assert "Stopped." in runner.command("stop").stdout
    assert not runner.pid_file.exists()
    assert runner.events() == ["started", "stopped", "started", "stopped"]
    assert "Stopped." in runner.command("status").stdout
    assert "Already stopped." in runner.command("stop").stdout
    assert (runner.root / "data/forwarder.db").is_file()
    assert (runner.root / "data/logs/forwarder.log").is_file()


def test_invalid_configuration_does_not_interrupt_running_process(runner):
    runner.command("start")
    pid = runner.pid_file.read_text()
    runner.env_file.write_text("TG_API_ID=invalid\n")
    runner.command("restart", expected=1)
    assert runner.pid_file.read_text() == pid
    assert pid.strip() in runner.command("status").stdout
    assert not runner.http_status()["authenticated"]
    assert "Already running" in runner.command("start").stdout
    runner.command("stop")
    assert runner.events() == ["started", "stopped"]
    runner.command("start", expected=1)
    assert not runner.pid_file.exists()


def test_stale_pid_file_never_stops_an_unrelated_process(runner):
    unrelated = subprocess.Popen(["sleep", "30"], cwd=runner.root)
    try:
        runner.pid_file.parent.mkdir(parents=True, exist_ok=True)
        runner.pid_file.write_text(str(unrelated.pid))
        assert "Stopped." in runner.command("status").stdout
        runner.command("stop")
        assert unrelated.poll() is None
        assert not runner.pid_file.exists()
        runner.pid_file.write_text(str(unrelated.pid))
        runner.command("start")
        assert int(runner.pid_file.read_text()) != unrelated.pid
        runner.command("stop")
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_control_lock_arguments_and_failed_start(runner):
    assert "Usage:" in runner.command("unknown", expected=2).stderr
    runner.command("start", "extra", expected=2)
    runner.pid_file.parent.mkdir(parents=True, exist_ok=True)
    with (runner.pid_file.parent / "control.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert "in progress" in runner.command("start", expected=1).stderr
        assert "Stopped." in runner.command("status").stdout
        assert not runner.pid_file.exists()
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", runner.port))
        occupied.listen()
        assert "exited during startup" in runner.command("start", expected=1).stderr
    assert not runner.pid_file.exists()
    assert "Stopped." in runner.command("status").stdout
    assert "Address already in use" in (runner.root / "data/logs/forwarder.log").read_text()
