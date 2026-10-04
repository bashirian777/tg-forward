"""One-time move of deployment fields out of an existing SQLite installation."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

from dotenv import set_key

from .models import RuntimeConfig
from .paths import PROJECT_ROOT, project_path
from .startup_config import DEFAULTS, StartupConfig, StartupConfigurationError, read_env_file

LEGACY_FIELDS = {
    "api_id": "TG_API_ID", "api_hash": "TG_API_HASH", "phone": "TG_PHONE",
    "bot_token": "TG_BOT_TOKEN", "admin_ids": "TG_ADMIN_IDS", "web_port": "WEB_PORT",
}
DEPLOYMENT_KEYS = set(LEGACY_FIELDS) | {"proxy", "session_path", "web_host"}


def prepare_env(db_path, env_file, *, project_root=PROJECT_ROOT, environ=None):
    """Prepare .env without touching SQLite or Telegram, retaining existing values."""
    db_path, env_file = project_path(db_path, project_root), project_path(env_file, project_root)
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT data FROM app_settings WHERE id=1").fetchone()
        if not row:
            raise ValueError("Database is not initialized")
        old = json.loads(row[0])
    if not DEPLOYMENT_KEYS & old.keys():
        raise ValueError("Deployment fields have already been migrated; configure .env.example")
    seeds = {name: str(old[key]) for key, name in LEGACY_FIELDS.items() if key in old and key != "admin_ids"}
    seeds["TG_ADMIN_IDS"] = ",".join(str(value) for value in old.get("admin_ids", []))
    seeds["DB_PATH"] = str(db_path)
    seeds["SESSION_PATH"] = str(project_path(old.get("session_path", "forwarder.session"), project_root))
    if old.get("web_host"):
        seeds["WEB_HOST"] = old["web_host"]
    if old.get("proxy"):
        proxy = old["proxy"]
        scheme = proxy.get("proxy_type", "socks5")
        if scheme not in ("socks5", "socks4", "http"):
            raise ValueError("Legacy proxy type is unsupported; review proxy settings before migration")
        host = proxy["addr"]
        if ":" in host:
            host = "[" + host + "]"
        auth = ""
        if proxy.get("username"):
            auth = quote(proxy["username"], safe="") + ":" + quote(proxy.get("password") or "", safe="") + "@"
        seeds["TG_PROXY_URL"] = f"{scheme}://{auth}{host}:{proxy['port']}"
    if env_file.is_symlink():
        raise ValueError("Environment file must not be a symlink")
    original = env_file.read_bytes() if env_file.exists() else None
    existing = read_env_file(env_file)
    conflicts = []
    for name, value in seeds.items():
        present = existing.get(name)
        if not present:
            continue
        if name == "SESSION_PATH" and "session_path" not in old:
            continue
        if name in ("DB_PATH", "SESSION_PATH"):
            equal = project_path(present, project_root) == project_path(value, project_root)
        elif name == "TG_ADMIN_IDS":
            equal = present.replace(" ", "") == value
        else:
            equal = present.strip() == value
        if not equal:
            conflicts.append(name)
    if conflicts:
        raise StartupConfigurationError("Migration conflicts in " + ", ".join(conflicts) + "; existing .env was preserved")
    values = dict(DEFAULTS, **seeds)
    values.update({key: value for key, value in existing.items() if key in DEFAULTS and value not in (None, "")})
    StartupConfig.from_values(values, project_root=project_root)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".env-migrate-", dir=env_file.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(original or b"# Deployment settings; runtime settings live in SQLite.\n")
        for name, value in values.items():
            if not existing.get(name):
                set_key(temporary, name, value, quote_mode="always")
        StartupConfig.load(temporary, environ={} if environ is None else environ, project_root=project_root)
        current = env_file.read_bytes() if env_file.exists() else None
        if current != original:
            raise ValueError("Environment file changed during migration; retry")
        if original is None:
            os.link(temporary, env_file)  # Refuse to replace a concurrently created file.
        else:
            os.replace(temporary, env_file)
        env_file.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()


def remove_deployment_fields(database, expected_digest=None):
    """Remove stale copies in one transaction, preserving all task/state tables."""
    with database.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM app_settings WHERE id=1").fetchone()
        if not row:
            raise ValueError("Database is not initialized")
        old = json.loads(row[0])
        digest = hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
        if expected_digest and digest != expected_digest:
            raise ValueError("Database configuration changed during migration; retry")
        if not DEPLOYMENT_KEYS & old.keys():
            return False
        allowed = RuntimeConfig.setting_names()
        current = {key: value for key, value in old.items() if key in allowed}
        db.execute("UPDATE app_settings SET data=?,revision=revision+1,updated_at=? WHERE id=1",
            (json.dumps(current, ensure_ascii=False), database._now()))
        db.execute("DELETE FROM app_config")
        for snapshot in db.execute("SELECT id,data FROM config_snapshots").fetchall():
            data = json.loads(snapshot["data"])
            data = {key: value for key, value in data.items() if key in allowed or key == "tasks"}
            db.execute("UPDATE config_snapshots SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), snapshot["id"]))
        def redact(value):
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items() if key not in DEPLOYMENT_KEYS}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        for log in db.execute("SELECT id,before_data,after_data FROM operation_logs").fetchall():
            for column in ("before_data", "after_data"):
                if log[column]:
                    cleaned = json.dumps(redact(json.loads(log[column])), ensure_ascii=False)
                    db.execute(f"UPDATE operation_logs SET {column}=? WHERE id=?", (cleaned, log["id"]))
        db.execute("DELETE FROM metadata WHERE key='legacy_imported'")
        db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('deployment_config_version','1')")
    return True
