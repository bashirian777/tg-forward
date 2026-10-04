"""Paths are anchored to the installation, independent of the shell's cwd."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path("data/forwarder.db")
DEFAULT_SESSION_PATH = Path("data/sessions/forwarder.session")


def project_path(value, root=PROJECT_ROOT):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(root) / path).resolve()
