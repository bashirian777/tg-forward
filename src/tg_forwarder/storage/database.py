"""SQLite storage for configuration, progress, transfers, and dedup records."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from tg_forwarder.config.models import RuntimeConfig
from tg_forwarder.config.paths import DEFAULT_DB_PATH, project_path
from tg_forwarder.tasks.validation import validate_source_reset


class ConfigurationConflict(ValueError):
    """The record changed after it was read by a management client."""


class Database:
    """Small transactional SQLite repository used by all application layers."""

    def __init__(self, path: str = str(DEFAULT_DB_PATH), *, create=True):
        self.path = str(project_path(path))
        if not create and not os.path.isfile(self.path):
            raise FileNotFoundError("Database not found; run 'init' or check DB_PATH")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS config_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_progress (
                    task_id TEXT PRIMARY KEY,
                    last_message_id INTEGER NOT NULL DEFAULT 0,
                    last_forward_time TEXT NOT NULL DEFAULT '',
                    forwarded_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS active_transfers (
                    task_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS dedup_records (
                    task_id TEXT NOT NULL,
                    file_unique_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, file_unique_id),
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS operation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    task_id TEXT,
                    before_data TEXT,
                    after_data TEXT,
                    result TEXT NOT NULL DEFAULT 'success',
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS task_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    message_id INTEGER,
                    file_index INTEGER,
                    filename TEXT,
                    error TEXT NOT NULL,
                    details TEXT,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS processed_messages (
                    task_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    PRIMARY KEY(task_id, message_id),
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS send_intents (
                    task_id TEXT NOT NULL,
                    intent_key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY(task_id, intent_key),
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_task_errors_task_created
                    ON task_errors(task_id, created_at DESC);
                """
            )
            for table in ("app_settings", "tasks"):
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if "revision" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
            db.execute(
                "INSERT OR IGNORE INTO app_settings(id, data, updated_at) "
                "SELECT id, data, updated_at FROM app_config"
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_metadata(self, key: str) -> Optional[str]:
        with self.connection() as db:
            row = db.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    @staticmethod
    def _validate_settings(data):
        if set(data) - RuntimeConfig.setting_names():
            raise ValueError("Only runtime settings may be saved in SQLite")

    def initialize_settings(self, data, password_format=None):
        """Insert defaults only once, including under concurrent initialization."""
        self._validate_settings(data)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("INSERT OR IGNORE INTO app_settings(id,data,updated_at) VALUES(1,?,?)",
                (json.dumps(data, ensure_ascii=False), self._now()))
            if cursor.rowcount and password_format:
                db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('web_password_format',?)", (password_format,))
            return cursor.rowcount == 1

    def verify(self):
        with self.connection() as db:
            checks = [row[0] for row in db.execute("PRAGMA integrity_check")]
            foreign_keys = [tuple(row) for row in db.execute("PRAGMA foreign_key_check")]
        return {"ok": checks == ["ok"] and not foreign_keys,
            "integrity": checks, "foreign_key_errors": foreign_keys}

    def configuration_snapshot(self):
        """Read configuration values and revisions from one SQLite snapshot."""
        with self.connection() as db:
            db.execute("BEGIN")
            app = db.execute("SELECT data,revision FROM app_settings WHERE id=1").fetchone()
            if app is None:
                raise FileNotFoundError("Database is not initialized; run 'init'")
            tasks = db.execute("SELECT task_id,data,revision FROM tasks ORDER BY task_id").fetchall()
            return (json.loads(app["data"]), app["revision"],
                {row["task_id"]: json.loads(row["data"]) for row in tasks},
                {row["task_id"]: row["revision"] for row in tasks})

    def get_app_config(self) -> Optional[dict]:
        with self.connection() as db:
            row = db.execute("SELECT data FROM app_settings WHERE id = 1").fetchone()
            return json.loads(row["data"]) if row else None

    def revision(self, task_id: str = None) -> int:
        with self.connection() as db:
            if task_id is None:
                row = db.execute("SELECT revision FROM app_settings WHERE id=1").fetchone()
            else:
                row = db.execute("SELECT revision FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return int(row[0]) if row else 0

    @staticmethod
    def _check_revision(db, table, key, expected):
        column = "task_id" if table == "tasks" else "id"
        row = db.execute(f"SELECT revision FROM {table} WHERE {column}=?", (key,)).fetchone()
        actual = int(row[0]) if row else 0
        if expected is not None and actual != expected:
            raise ConfigurationConflict("配置已被其他操作修改，请重新读取后再保存")
        return actual

    def update_app_config(self, data: dict, expected_revision=None) -> None:
        self._validate_settings(data)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, "app_settings", 1, expected_revision)
            db.execute(
                "INSERT INTO app_settings(id, data, updated_at) VALUES(1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, revision=app_settings.revision+1",
                (json.dumps(data, ensure_ascii=False), self._now()),
            )
            db.execute(
                "INSERT INTO config_snapshots(created_at, reason, data) VALUES(?, ?, ?)",
                (self._now(), "update_app_config", json.dumps({key: value for key, value in data.items() if key != "web_password"}, ensure_ascii=False)),
            )

    def list_tasks(self) -> list:
        with self.connection() as db:
            return [json.loads(row["data"]) for row in db.execute("SELECT data FROM tasks ORDER BY task_id")]

    def get_task(self, task_id: str) -> Optional[dict]:
        with self.connection() as db:
            row = db.execute("SELECT data FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def save_task(self, data: dict, expected_revision=None, source_reset=None) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, "tasks", data["task_id"], expected_revision)
            old = db.execute("SELECT data FROM tasks WHERE task_id=?", (data["task_id"],)).fetchone()
            validate_source_reset(json.loads(old["data"]) if old else None, data, source_reset)
            db.execute(
                "INSERT INTO tasks(task_id, data, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, revision=tasks.revision+1",
                (data["task_id"], json.dumps(data, ensure_ascii=False), self._now()),
            )
            if source_reset is not None:
                self._delete_task_state(db, data["task_id"], source_reset["clear_dedup"])
                db.execute("INSERT INTO task_progress(task_id,last_message_id,updated_at) VALUES(?,?,?)",
                           (data["task_id"], source_reset["last_message_id"], self._now()))

    def delete_task(self, task_id: str, expected_revision=None) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actual = self._check_revision(db, "tasks", task_id, expected_revision)
            if not actual:
                raise ValueError(f"Task {task_id} not found")
            db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    def completed_ids(self, task_id: str) -> set:
        with self.connection() as db:
            return {row[0] for row in db.execute("SELECT message_id FROM processed_messages WHERE task_id=?", (task_id,))}

    def complete_group(self, task_id, message_ids, outcome, count, ordered_ids) -> dict:
        """Commit receipts, count and the safe checkpoint in one transaction."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            done = {row[0] for row in db.execute("SELECT message_id FROM processed_messages WHERE task_id=?", (task_id,))}
            fresh = not set(message_ids).issubset(done)
            db.executemany(
                "INSERT OR IGNORE INTO processed_messages(task_id, message_id, outcome) VALUES(?, ?, ?)",
                [(task_id, value, outcome) for value in message_ids],
            )
            done.update(message_ids)
            row = db.execute("SELECT * FROM task_progress WHERE task_id=?", (task_id,)).fetchone()
            progress = dict(row) if row else {"task_id": task_id, "last_message_id": 0, "last_forward_time": "", "forwarded_count": 0}
            checkpoint = progress["last_message_id"]
            for value in sorted(set(ordered_ids)):
                if value <= checkpoint:
                    continue
                if value not in done:
                    break
                checkpoint = value
            progress["last_message_id"] = checkpoint
            if fresh and count:
                progress["forwarded_count"] += count
                progress["last_forward_time"] = self._now()
            db.execute(
                "INSERT INTO task_progress(task_id,last_message_id,last_forward_time,forwarded_count,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET last_message_id=excluded.last_message_id,last_forward_time=excluded.last_forward_time,forwarded_count=excluded.forwarded_count,updated_at=excluded.updated_at",
                (task_id, checkpoint, progress["last_forward_time"], progress["forwarded_count"], self._now()),
            )
            db.execute("DELETE FROM processed_messages WHERE task_id=? AND message_id<=?", (task_id, checkpoint))
            for intent in db.execute("SELECT intent_key,data FROM send_intents WHERE task_id=?", (task_id,)).fetchall():
                saved = json.loads(intent["data"])
                if saved.get("sent") and saved.get("message_ids") and max(saved["message_ids"]) <= checkpoint:
                    db.execute("DELETE FROM send_intents WHERE task_id=? AND intent_key=?", (task_id, intent["intent_key"]))
            return progress

    @staticmethod
    def _delete_task_state(db, task_id, clear_dedup=False):
        for table in ("processed_messages", "send_intents", "active_transfers", "task_progress"):
            db.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,))
        if clear_dedup:
            db.execute("DELETE FROM dedup_records WHERE task_id=?", (task_id,))

    def reset_checkpoint(self, task_id, last_message_id, forwarded_count):
        """Replace receipts, sending state and checkpoint in one transaction."""
        for name, value in (("last_message_id", last_message_id), ("forwarded_count", forwarded_count)):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._delete_task_state(db, task_id)
            db.execute("INSERT INTO task_progress(task_id,last_message_id,last_forward_time,forwarded_count,updated_at) VALUES(?,?,'',?,?)",
                (task_id, last_message_id, forwarded_count, self._now()))
        return {"task_id": task_id, "last_message_id": last_message_id,
            "last_forward_time": "", "forwarded_count": forwarded_count}

    def reset_task_state(self, task_id, clear_dedup=False):
        with self.connection() as db:
            self._delete_task_state(db, task_id, clear_dedup)

    def get_intent(self, task_id, key):
        with self.connection() as db:
            row = db.execute("SELECT data FROM send_intents WHERE task_id=? AND intent_key=?", (task_id, key)).fetchone()
            return json.loads(row[0]) if row else None

    def save_intent(self, task_id, key, data):
        with self.connection() as db:
            db.execute(
                "INSERT INTO send_intents(task_id,intent_key,data) VALUES(?,?,?) "
                "ON CONFLICT(task_id,intent_key) DO UPDATE SET data=excluded.data",
                (task_id, key, json.dumps(data)),
            )

    def get_progress(self, task_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM task_progress WHERE task_id = ?", (task_id,)).fetchone()
            if row:
                return dict(row)
        return {"task_id": task_id, "last_message_id": 0, "last_forward_time": "", "forwarded_count": 0}

    def list_progress(self) -> Dict[str, dict]:
        with self.connection() as db:
            return {row["task_id"]: dict(row) for row in db.execute("SELECT * FROM task_progress")}

    def save_progress(self, data: dict) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO task_progress(task_id, last_message_id, last_forward_time, forwarded_count, updated_at) VALUES(?, ?, ?, ?, ?)",
                (data["task_id"], int(data.get("last_message_id", 0)), data.get("last_forward_time", ""), int(data.get("forwarded_count", 0)), self._now()),
            )

    def delete_progress(self, task_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM task_progress WHERE task_id = ?", (task_id,))

    def get_transfer(self, task_id: str) -> Optional[dict]:
        with self.connection() as db:
            row = db.execute("SELECT data FROM active_transfers WHERE task_id = ?", (task_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def list_transfers(self) -> Dict[str, dict]:
        with self.connection() as db:
            return {row["task_id"]: json.loads(row["data"]) for row in db.execute("SELECT task_id, data FROM active_transfers")}

    def save_transfer(self, task_id: str, data: dict) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO active_transfers(task_id, data, updated_at) VALUES(?, ?, ?)",
                (task_id, json.dumps(data, ensure_ascii=False), self._now()),
            )

    def delete_transfer(self, task_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM active_transfers WHERE task_id = ?", (task_id,))

    def dedup_ids(self, task_id: str) -> set:
        with self.connection() as db:
            return {row["file_unique_id"] for row in db.execute("SELECT file_unique_id FROM dedup_records WHERE task_id = ?", (task_id,))}

    def list_dedup(self, task_id: str, limit: int = 500) -> list:
        limit = max(1, min(int(limit), 5000))
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT file_unique_id, created_at FROM dedup_records WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            )]

    def add_dedup_ids(self, task_id: str, values: Iterable[str]) -> None:
        with self.connection() as db:
            db.executemany(
                "INSERT OR IGNORE INTO dedup_records(task_id, file_unique_id, created_at) VALUES(?, ?, ?)",
                [(task_id, str(value), self._now()) for value in values],
            )

    def clear_dedup(self, task_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM dedup_records WHERE task_id = ?", (task_id,))

    def dedup_count(self, task_id: str) -> int:
        with self.connection() as db:
            row = db.execute("SELECT COUNT(*) AS count FROM dedup_records WHERE task_id = ?", (task_id,)).fetchone()
            return int(row["count"])

    def log_operation(self, action: str, task_id: str = None, actor: str = "system",
                      before_data=None, after_data=None, result: str = "success", error: str = None) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO operation_logs(created_at, actor, action, task_id, before_data, after_data, result, error) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (self._now(), actor, action, task_id,
                 json.dumps(before_data, ensure_ascii=False) if before_data is not None else None,
                 json.dumps(after_data, ensure_ascii=False) if after_data is not None else None,
                 result, error),
            )

    def add_task_error(self, task_id: str, stage: str, error: str,
                       message_id: int = None, file_index: int = None,
                       filename: str = "", details: str = "") -> int:
        """Persist a Telegram/download/upload error for Web inspection."""
        with self.connection() as db:
            cursor = db.execute(
                """INSERT INTO task_errors(
                    task_id, created_at, stage, message_id, file_index,
                    filename, error, details
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, self._now(), stage, message_id, file_index,
                 filename or "", str(error), details or ""),
            )
            return int(cursor.lastrowid)

    def list_task_errors(self, task_id: str, limit: int = 100) -> list:
        limit = max(1, min(int(limit), 500))
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                """SELECT id, task_id, created_at, stage, message_id,
                          file_index, filename, error, details, resolved
                   FROM task_errors
                   WHERE task_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (task_id, limit),
            )]

    def task_error_summary(self, task_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                """SELECT COUNT(*) AS count,
                          SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) AS unresolved
                   FROM task_errors WHERE task_id = ?""",
                (task_id,),
            ).fetchone()
            latest = db.execute(
                """SELECT id, created_at, stage, message_id, file_index,
                          filename, error FROM task_errors
                   WHERE task_id = ? ORDER BY id DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
        return {
            "task_id": task_id,
            "count": int(row["count"] or 0),
            "unresolved": int(row["unresolved"] or 0),
            "latest": dict(latest) if latest else None,
        }

    def clear_task_errors(self, task_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM task_errors WHERE task_id = ?", (task_id,))

    def resolve_task_errors(self, task_id: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE task_errors SET resolved = 1 WHERE task_id = ? AND resolved = 0",
                (task_id,),
            )

    def list_logs(self, limit: int = 100) -> list:
        limit = max(1, min(int(limit), 500))
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM operation_logs ORDER BY id DESC LIMIT ?", (limit,))]
