"""Password hashing and explicit, transactional migration of legacy plaintext."""
import json
from werkzeug.security import check_password_hash, generate_password_hash

FORMAT_KEY = "web_password_format"
FORMAT_VERSION = "1"


def hash_password(password):
    return generate_password_hash(password, method="pbkdf2:sha256:600000") if password else ""


def verify_password(encoded, password):
    return isinstance(password, str) and bool(encoded) and check_password_hash(encoded, password)


def migrate_passwords(database):
    with database.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        marker = db.execute("SELECT value FROM metadata WHERE key=?", (FORMAT_KEY,)).fetchone()
        if marker and marker[0] == FORMAT_VERSION:
            return
        row = db.execute("SELECT data FROM app_settings WHERE id=1").fetchone()
        if not row:
            return
        settings = json.loads(row[0])
        settings["web_password"] = hash_password(settings.get("web_password", ""))
        db.execute("UPDATE app_settings SET data=?, revision=revision+1 WHERE id=1", (json.dumps(settings, ensure_ascii=False),))
        # Remove obsolete copies, rather than keeping hashes of old passwords.
        def redact(value):
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items() if key != "web_password"}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        for table, columns in (("app_config", ("data",)), ("config_snapshots", ("data",)), ("operation_logs", ("before_data", "after_data"))):
            for saved in db.execute(f"SELECT id,{','.join(columns)} FROM {table}").fetchall():
                for column in columns:
                    if saved[column]:
                        clean = json.dumps(redact(json.loads(saved[column])), ensure_ascii=False)
                        db.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (clean, saved["id"]))
        db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", (FORMAT_KEY, FORMAT_VERSION))
