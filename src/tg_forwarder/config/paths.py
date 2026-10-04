"""Source checkouts use the project root; installed distributions use cwd."""
from pathlib import Path

_checkout = Path(__file__).resolve().parents[3]
PROJECT_ROOT = _checkout if (_checkout / "pyproject.toml").is_file() else Path.cwd().resolve()
DEFAULT_DB_PATH = Path("data/forwarder.db")
DEFAULT_SESSION_PATH = Path("data/sessions/forwarder.session")


def project_path(value, root=PROJECT_ROOT):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(root) / path).resolve()
