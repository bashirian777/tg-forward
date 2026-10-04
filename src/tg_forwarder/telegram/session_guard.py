"""Exclusive ownership of a Telegram session across CLI, server and benchmarks."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from tg_forwarder.config.paths import PROJECT_ROOT

COMMANDS = {"init", "login", "serve", "bot", "add", "list", "start", "delete", "verify-db", "migrate-env"}


def project_processes(commands, project_root=PROJECT_ROOT):
    """Find project CLI commands, including instances predating session locks."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().decode().split("\0")
            cwd = (entry / "cwd").resolve()
        except (FileNotFoundError, PermissionError, ProcessLookupError, UnicodeError):
            continue
        if cwd != Path(project_root).resolve():
            continue
        entrypoints = {"src.main", "tg_forwarder", "tg_forwarder.cli"}
        index = next((i for i, arg in enumerate(argv) if arg in entrypoints or Path(arg).name == "tg-forward"), None)
        if index is None:
            continue
        arguments = iter(argv[index + 1:])
        for argument in arguments:
            if argument in ("--env-file", "--log-level", "-l"):
                next(arguments, None)
            elif argument in COMMANDS:
                if argument in commands:
                    yield int(entry.name)
                break


@contextmanager
def session_guard(session_path, project_root=PROJECT_ROOT):
    if any(project_processes({"bot", "serve", "start", "login"}, project_root)):
        raise ValueError("The project's Telegram service is running; stop it before using this session")
    lock_path = Path(str(session_path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Telegram session is in use by another process") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
