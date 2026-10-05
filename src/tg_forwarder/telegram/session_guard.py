"""Exclusive ownership of a Telegram session across CLI, server and benchmarks."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from tg_forwarder.config.paths import PROJECT_ROOT, project_path
from tg_forwarder.config.startup import DEFAULTS, StartupConfigurationError, read_env_file

PROC_ROOT = Path("/proc")

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


def _session_path(value, project_root, environ=None):
    # Expand HOME using the target process, not the inspecting CLI's environment.
    value = str(value).strip()
    if environ is not None and (value == "~" or value.startswith("~/")):
        if not environ.get("HOME"):
            raise ValueError("Cannot resolve the process's session home directory")
        value = environ["HOME"] + value[1:]
    path = project_path(value, project_root)
    if not str(path).endswith(".session"):
        path = path.with_name(path.name + ".session")
    return path.resolve()


def _process_command(argv):
    entrypoints = {"src.main", "tg_forwarder", "tg_forwarder.cli"}
    index = next((i for i, arg in enumerate(argv)
        if arg in entrypoints or Path(arg).name == "tg-forward"), None)
    if index is None:
        return None
    env_file = None
    arguments = iter(argv[index + 1:])
    for argument in arguments:
        if argument == "--env-file":
            env_file = next(arguments, None)
        elif argument.startswith("--env-file="):
            env_file = argument.split("=", 1)[1]
        elif argument in ("--log-level", "-l"):
            next(arguments, None)
        elif argument in COMMANDS:
            return argument, env_file
    return None


def _process_root(argv, cwd, environ, project_root):
    # Source checkouts resolve paths against PROJECT_ROOT even when launched
    # elsewhere. Installed distributions resolve them against the process cwd.
    candidates = []
    for argument in argv[:2]:
        if "/" in argument:
            executable = Path(argument)
            if not executable.is_absolute():
                executable = cwd / executable
            candidates.extend(executable.absolute().parents)
    for value in environ.get("PYTHONPATH", "").split(os.pathsep):
        if value:
            path = Path(value)
            path = path if path.is_absolute() else cwd / path
            candidates.extend((path, path.parent))
    candidates.append(cwd)
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src/tg_forwarder").is_dir():
            return candidate.resolve()
    root = Path(project_root).resolve()
    if (root / "pyproject.toml").is_file() and (root / "src/tg_forwarder").is_dir():
        return root
    # An explicit project_root is also useful for isolated callers/tests.
    return cwd if root == PROJECT_ROOT.resolve() else root


def _open_sessions(entry):
    try:
        descriptors = list((entry / "fd").iterdir())
    except OSError:
        return set()
    sessions = set()
    for descriptor in descriptors:
        try:
            path = descriptor.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if path.name.endswith(".session"):
            sessions.add(path)
    return sessions


def legacy_project_processes(session_path, project_root=PROJECT_ROOT):
    """Find CLI owners of this real session, including versions without locks.

    Process cwd alone cannot identify an account. Read each process's own
    deployment values; never inherit SESSION_PATH from the inspecting process.
    Open SQLite sessions take precedence over configuration changed after start.
    """
    expected = _session_path(session_path, project_root)
    for entry in PROC_ROOT.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().decode().split("\0")
            cwd = (entry / "cwd").resolve(strict=True)
        except (OSError, UnicodeError, RuntimeError):
            continue
        command = _process_command(argv)
        if command is None or command[0] not in {"bot", "serve", "start", "login"}:
            continue
        sessions = _open_sessions(entry)
        if sessions:
            if expected in sessions:
                yield int(entry.name)
            continue
        try:
            environment = dict(item.split("=", 1) for item in
                (entry / "environ").read_bytes().decode().split("\0") if "=" in item)
            root = _process_root(argv, cwd, environment, project_root)
            env_file = command[1] or ".env"
            # Use the same HOME expansion and project-root rules as startup.
            if env_file == "~" or env_file.startswith("~/"):
                if not environment.get("HOME"):
                    continue
                env_file = environment["HOME"] + env_file[1:]
            values = read_env_file(project_path(env_file, root))
            value = environment.get("SESSION_PATH", values.get("SESSION_PATH", DEFAULTS["SESSION_PATH"]))
            if not value or not value.strip():
                continue
            actual = _session_path(value, root, environment)
        except (OSError, UnicodeError, ValueError, RuntimeError, StartupConfigurationError):
            continue
        if actual == expected:
            yield int(entry.name)


@contextmanager
def session_guard(session_path, project_root=PROJECT_ROOT):
    lock_path = Path(str(_session_path(session_path, project_root)) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Telegram session is in use by another process") from None
        try:
            if any(legacy_project_processes(session_path, project_root)):
                raise ValueError("The project's Telegram service is running with this session; stop it before using this session")
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
