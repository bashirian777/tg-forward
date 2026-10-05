"""Offline session ownership checks for locks and pre-lock CLI instances."""
from contextlib import contextmanager
import importlib
import os
from pathlib import Path
import selectors
import subprocess
import sys

import pytest

from tests.support import startup


guard = importlib.import_module("tg_forwarder.telegram.session_guard")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def proc(tmp_path, monkeypatch):
    path = tmp_path / "proc"
    path.mkdir()
    monkeypatch.setattr(guard, "PROC_ROOT", path)
    return path


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "checkout"
    (root / "src/tg_forwarder").mkdir(parents=True)
    (root / "pyproject.toml").touch()
    return root


def process(proc, cwd, *, arguments=None, environment=None, sessions=(), pid=900001):
    entry = proc / str(pid)
    entry.mkdir()
    argv = arguments or ["python", "-m", "tg_forwarder.cli", "serve"]
    (entry / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
    (entry / "environ").write_bytes("\0".join(f"{key}={value}" for key, value in (environment or {}).items()).encode() + b"\0")
    (entry / "cwd").symlink_to(cwd, target_is_directory=True)
    (entry / "fd").mkdir()
    for index, session in enumerate(sessions):
        (entry / "fd" / str(index)).symlink_to(session)
    return pid


@contextmanager
def offline_owner(tmp_path, session, *, locked=True):
    code = '''
from contextlib import nullcontext
from pathlib import Path
import sys
from tg_forwarder.telegram.session_guard import session_guard
session = Path(sys.argv[-2])
with session_guard(session) if sys.argv[-1] == "locked" else nullcontext():
    print("ready", flush=True)
    sys.stdin.readline()
'''
    environment = dict(os.environ, SESSION_PATH=str(session))
    child = subprocess.Popen([sys.executable, "-u", "-c", code, "tg_forwarder.cli", "serve",
        str(session), "locked" if locked else "legacy"], cwd=ROOT, env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(child.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=10), "Offline session owner did not start"
        line = child.stdout.readline().strip()
        if line != "ready":
            _, err = child.communicate(timeout=5)
            pytest.fail(f"Offline session owner exited before readiness: {err}")
        yield child
    finally:
        if child.poll() is None:
            try:
                child.communicate("\n", timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate(timeout=5)


@pytest.mark.parametrize("same_session", [True, False])
def test_independent_offline_processes_share_cwd_but_only_same_session_is_rejected(tmp_path, same_session):
    session = startup(tmp_path, SESSION_PATH="owner").session_path
    requested = session if same_session else startup(tmp_path, SESSION_PATH="other").session_path
    with offline_owner(tmp_path, session):
        if same_session:
            with pytest.raises(ValueError, match="in use"):
                with guard.session_guard(requested):
                    pytest.fail("Concurrent session owner was accepted")
        else:
            with guard.session_guard(requested):
                pass
    with guard.session_guard(session):
        pass


def test_legacy_offline_process_without_lock_still_blocks_its_session(tmp_path):
    session = startup(tmp_path, SESSION_PATH="legacy").session_path
    with offline_owner(tmp_path, session, locked=False):
        assert not Path(str(session) + ".lock").exists()
        with pytest.raises(ValueError, match="running with this session"):
            with guard.session_guard(session):
                pytest.fail("Legacy owner was accepted")
        with guard.session_guard(tmp_path / "other"):
            pass
    with guard.session_guard(session):
        pass


def test_suffix_and_symlink_aliases_use_the_same_lock(proc, tmp_path):
    session = tmp_path / "account.session"
    session.touch()
    alias = tmp_path / "alias.session"
    alias.symlink_to(session)
    with guard.session_guard(tmp_path / "account", project_root=tmp_path):
        for requested in (session, alias):
            with pytest.raises(ValueError, match="in use"):
                with guard.session_guard(requested, project_root=tmp_path):
                    pytest.fail("Session alias bypassed the lock")


@pytest.mark.parametrize("entrypoint", [
    ["python", "-m", "src.main"],
    ["python", "-m", "tg_forwarder"],
    ["python", "-m", "tg_forwarder.cli"],
    ["tg-forward"],
])
@pytest.mark.parametrize("env_option", [["--env-file", "custom.env"], ["--env-file=custom.env"]])
def test_legacy_env_file_is_relative_to_project_root_even_from_other_cwd(proc, project, tmp_path, entrypoint, env_option):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project / "custom.env").write_text("SESSION_PATH='accounts/legacy'\n")
    (elsewhere / "custom.env").write_text("SESSION_PATH='wrong'\n")
    pid = process(proc, elsewhere, arguments=entrypoint + ["--log-level", "ERROR"] + env_option + ["serve"])
    expected = project / "accounts/legacy.session"
    assert list(guard.legacy_project_processes(expected, project)) == [pid]
    with pytest.raises(ValueError, match="running with this session"):
        with guard.session_guard(expected, project_root=project):
            pytest.fail("Legacy owner was accepted")
    with guard.session_guard(project / "independent", project_root=project):
        pass


@pytest.mark.parametrize("value", ["accounts/environment", "accounts/environment.session", "absolute", "~/account"])
def test_legacy_process_environment_overrides_dotenv_and_inspecting_environment(proc, project, tmp_path, monkeypatch, value):
    env_file = tmp_path / "external.env"
    env_file.write_text("SESSION_PATH='wrong'\n")
    home = tmp_path / "home"
    home.mkdir()
    value = str(tmp_path / "absolute.session") if value == "absolute" else value
    environment = {"SESSION_PATH": value, "HOME": str(home)}
    pid = process(proc, project, arguments=["tg-forward", "--env-file", str(env_file), "login"], environment=environment)
    monkeypatch.setenv("SESSION_PATH", "inspectors-account")
    expected = home / "account.session" if value.startswith("~/") else startup(project, SESSION_PATH=value).session_path
    assert list(guard.legacy_project_processes(expected, project)) == [pid]
    assert list(guard.legacy_project_processes(project / "wrong", project)) == []


def test_default_session_uses_project_root_not_cwd_or_inspector_environment(proc, project, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("SESSION_PATH", str(tmp_path / "inspectors-account"))
    pid = process(proc, elsewhere)
    assert list(guard.legacy_project_processes(project / "data/sessions/forwarder.session", project)) == [pid]
    assert list(guard.legacy_project_processes(elsewhere / "data/sessions/forwarder.session", project)) == []


def test_open_session_is_authoritative_for_older_versions_and_changed_configuration(proc, project):
    session = project / "forwarder.session"
    session.touch()
    alias = project / "alias.session"
    alias.symlink_to(session)
    pid = process(proc, project, environment={"SESSION_PATH": "changed"}, sessions=[alias])
    assert list(guard.legacy_project_processes(session, project)) == [pid]
    assert list(guard.legacy_project_processes(project / "changed", project)) == []


def test_another_checkout_resolves_its_own_relative_paths(proc, project, tmp_path):
    other = tmp_path / "other-checkout"
    (other / "src/tg_forwarder").mkdir(parents=True)
    (other / "pyproject.toml").touch()
    pid = process(proc, other, environment={"SESSION_PATH": "account"})
    assert list(guard.legacy_project_processes(other / "account", project)) == [pid]
    assert list(guard.legacy_project_processes(project / "account", project)) == []


def test_pythonpath_identifies_checkout_when_process_runs_elsewhere(proc, project, tmp_path):
    other = tmp_path / "other-checkout"
    (other / "src/tg_forwarder").mkdir(parents=True)
    (other / "pyproject.toml").touch()
    pid = process(proc, tmp_path, environment={"PYTHONPATH": str(other / "src"), "SESSION_PATH": "account"})
    assert list(guard.legacy_project_processes(other / "account", project)) == [pid]
    assert list(guard.legacy_project_processes(project / "account", project)) == []


@pytest.mark.parametrize("arguments", [
    ["python", "unrelated.py", "serve"],
    ["tg-forward", "list"],
    ["tg-forward", "--env-file", "serve", "verify-db"],
])
def test_non_session_commands_and_option_values_are_not_legacy_owners(proc, project, arguments):
    process(proc, project, arguments=arguments)
    assert list(guard.legacy_project_processes(project / "data/sessions/forwarder.session", project)) == []


def test_exited_or_unreadable_process_entries_are_ignored(proc, project):
    (proc / "900001").mkdir()
    assert list(guard.legacy_project_processes(project / "account", project)) == []
