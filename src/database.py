"""SQLite storage for configuration, progress, transfers, and dedup records."""
import json
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional


class ConfigurationConflict(ValueError):
    """The record changed after it was read by a management client."""


class Database:
    """Small transactional SQLite repository used by all application layers."""

    def __init__(self, path: str = "config/forwarder.db"):
        self.path = os.path.abspath(path)
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
        return datetime.utcnow().isoformat() + "Z"

    def get_metadata(self, key: str) -> Optional[str]:
        with self.connection() as db:
            row = db.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def migration_info(self) -> Optional[dict]:
        value = self.get_metadata("legacy_imported")
        return json.loads(value) if value else None

    def ensure_legacy_migration(self, config_path: str = "config/config.json") -> bool:
        """Import legacy JSON only into an empty database, then preserve a backup."""
        if self.get_metadata("legacy_imported"):
            return False
        if not os.path.exists(config_path):
            return False

        # A database created or changed by the current application is already
        # authoritative, even if it predates the migration marker. Never let
        # an old JSON file overwrite data changed through Web or CLI.
        with self.connection() as db:
            has_data = any(
                db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                for table in ("app_settings", "tasks", "task_progress", "active_transfers", "dedup_records")
            )
            if has_data:
                now = self._now()
                db.execute(
                    "INSERT OR IGNORE INTO metadata(key, value) VALUES('legacy_imported', ?)",
                    (json.dumps({"at": now, "source": "existing_database"}, ensure_ascii=False),),
                )
                return False

        config_dir = os.path.dirname(os.path.abspath(config_path))
        progress_path = os.path.join(config_dir, "progress.json")
        download_path = os.path.join(config_dir, "progress_download.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            config_data = json.load(handle)

        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(config_dir, "legacy-backups", stamp)
        os.makedirs(backup_dir, mode=0o700, exist_ok=True)
        for source in (config_path, progress_path, download_path):
            if os.path.exists(source):
                shutil.copy2(source, os.path.join(backup_dir, os.path.basename(source)))
        for source in Path(config_dir).glob("dedup_*.json"):
            shutil.copy2(source, os.path.join(backup_dir, source.name))

        tasks = config_data.get("tasks", [])
        progress_data = self._read_json(progress_path, {})
        transfer_data = self._read_json(download_path, {})
        now = self._now()

        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO app_settings(id, data, updated_at) VALUES(1, ?, ?)",
                (json.dumps({key: value for key, value in config_data.items() if key != "tasks"}, ensure_ascii=False), now),
            )
            db.execute(
                "INSERT INTO config_snapshots(created_at, reason, data) VALUES(?, ?, ?)",
                (now, "legacy_migration", json.dumps(config_data, ensure_ascii=False)),
            )
            for task in tasks:
                task_id = str(task["task_id"])
                db.execute(
                    "INSERT INTO tasks(task_id, data, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(task_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                    (task_id, json.dumps(task, ensure_ascii=False), now),
                )

            # Preserve progress even if a legacy file contains a task removed
            # from config; create a disabled placeholder for manual recovery.
            for task_id, progress in progress_data.items():
                if not db.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone():
                    placeholder = {
                        "task_id": task_id, "source_channel": -1,
                        "target_channel": -1, "min_delay": 10.0,
                        "max_delay": 20.0, "enabled": False,
                        "note": "迁移保留的孤立进度"
                    }
                    db.execute(
                        "INSERT OR IGNORE INTO tasks(task_id, data, updated_at) VALUES(?, ?, ?)",
                        (task_id, json.dumps(placeholder, ensure_ascii=False), now),
                    )
                db.execute(
                    "INSERT OR REPLACE INTO task_progress(task_id, last_message_id, last_forward_time, forwarded_count, updated_at) VALUES(?, ?, ?, ?, ?)",
                    (task_id, int(progress.get("last_message_id", 0)), str(progress.get("last_forward_time", "")), int(progress.get("forwarded_count", 0)), now),
                )

            for task_id, transfer in transfer_data.items():
                snapshot = dict(transfer)
                snapshot["state"] = "interrupted"
                snapshot["legacy_state"] = transfer.get("type", "unknown")
                if not db.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone():
                    continue
                db.execute(
                    "INSERT OR REPLACE INTO active_transfers(task_id, data, updated_at) VALUES(?, ?, ?)",
                    (task_id, json.dumps(snapshot, ensure_ascii=False), now),
                )

            for source in Path(config_dir).glob("dedup_*.json"):
                task_id = source.stem[len("dedup_"):]
                if not db.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone():
                    continue
                values = self._read_json(str(source), {}).get("file_unique_ids", [])
                db.executemany(
                    "INSERT OR IGNORE INTO dedup_records(task_id, file_unique_id, created_at) VALUES(?, ?, ?)",
                    [(task_id, str(value), now) for value in values],
                )
            db.execute(
                "INSERT INTO metadata(key, value) VALUES('legacy_imported', ?)",
                (json.dumps({"at": now, "backup_dir": backup_dir}, ensure_ascii=False),),
            )
        return True

    @staticmethod
    def _read_json(path: str, default):
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return default

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
                (self._now(), "update_app_config", json.dumps(data, ensure_ascii=False)),
            )

    def list_tasks(self) -> list:
        with self.connection() as db:
            return [json.loads(row["data"]) for row in db.execute("SELECT data FROM tasks ORDER BY task_id")]

    def get_task(self, task_id: str) -> Optional[dict]:
        with self.connection() as db:
            row = db.execute("SELECT data FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def save_task(self, data: dict, expected_revision=None) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, "tasks", data["task_id"], expected_revision)
            db.execute(
                "INSERT INTO tasks(task_id, data, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, revision=tasks.revision+1",
                (data["task_id"], json.dumps(data, ensure_ascii=False), self._now()),
            )

    def save_config(self, app_data: dict, tasks: Iterable[dict]) -> None:
        """Bootstrap/import a snapshot without deleting absent tasks or child rows."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            now = self._now()
            db.execute(
                "INSERT INTO app_settings(id, data, updated_at) VALUES(1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, revision=app_settings.revision+1",
                (json.dumps(app_data, ensure_ascii=False), now),
            )
            for task in tasks:
                db.execute(
                    "INSERT INTO tasks(task_id, data, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(task_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, revision=tasks.revision+1",
                    (task["task_id"], json.dumps(task, ensure_ascii=False), now),
                )

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
            return progress

    def reset_task_state(self, task_id, clear_dedup=False):
        with self.connection() as db:
            for table in ("processed_messages", "send_intents", "active_transfers", "task_progress"):
                db.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,))
            if clear_dedup:
                db.execute("DELETE FROM dedup_records WHERE task_id=?", (task_id,))

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

    def sync_legacy(self, config_path: str = "config/config.json") -> str:
        """Synchronize the authoritative SQLite state into legacy JSON files."""
        config_path = os.path.abspath(config_path)
        config_dir = os.path.dirname(config_path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_root = os.path.join(config_dir, "json-backups")
        backup_dir = os.path.join(backup_root, stamp)
        suffix = 1
        while os.path.exists(backup_dir):
            backup_dir = os.path.join(backup_root, f"{stamp}-{suffix}")
            suffix += 1
        export_dir = os.path.join(config_dir, ".json-sync", os.path.basename(backup_dir))
        os.makedirs(backup_dir, mode=0o700, exist_ok=True)
        os.makedirs(export_dir, mode=0o700, exist_ok=True)

        legacy_files = [
            config_path,
            os.path.join(config_dir, "progress.json"),
            os.path.join(config_dir, "progress_download.json"),
        ]
        legacy_files.extend(str(path) for path in Path(config_dir).glob("dedup_*.json"))
        for source in legacy_files:
            if os.path.exists(source):
                shutil.copy2(source, os.path.join(backup_dir, os.path.basename(source)))

        self.export_legacy(export_dir)
        output_files = {"config.json", "progress.json", "progress_download.json"}
        output_files.update(path.name for path in Path(export_dir).glob("dedup_*.json"))
        staged = []
        try:
            for name in output_files:
                target = config_path if name == "config.json" else os.path.join(config_dir, name)
                temporary = target + f".sync-{os.getpid()}.tmp"
                shutil.copy2(os.path.join(export_dir, name), temporary)
                staged.append((temporary, target))
            for temporary, target in staged:
                os.replace(temporary, target)
            for source in Path(config_dir).glob("dedup_*.json"):
                if source.name not in output_files:
                    source.unlink()
        finally:
            for temporary, _ in staged:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            shutil.rmtree(export_dir, ignore_errors=True)
        self.log_operation(
            "sync_json", after_data={"config_path": config_path, "backup_dir": backup_dir}
        )
        return backup_dir

    def verify_legacy(self, config_path: str = "config/config.json") -> dict:
        """Compare legacy config/progress with the imported database values."""
        source = self._read_json(config_path, {})
        source_tasks = {str(item["task_id"]): item for item in source.get("tasks", [])}
        database_tasks = {str(item["task_id"]): item for item in self.list_tasks()}
        source_progress = self._read_json(os.path.join(os.path.dirname(config_path), "progress.json"), {})
        database_progress = self.list_progress()
        task_checks = {task_id: database_tasks.get(task_id) == item for task_id, item in source_tasks.items()}
        progress_checks = {}
        for task_id, item in source_progress.items():
            actual = database_progress.get(task_id, {})
            progress_checks[task_id] = all([
                int(actual.get("last_message_id", -1)) == int(item.get("last_message_id", 0)),
                int(actual.get("forwarded_count", -1)) == int(item.get("forwarded_count", 0)),
                actual.get("last_forward_time", "") == item.get("last_forward_time", ""),
            ])
        return {
            "tasks_source": len(source_tasks), "tasks_database": len(database_tasks),
            "progress_source": len(source_progress), "progress_database": len(database_progress),
            "task_checks": task_checks, "progress_checks": progress_checks,
            "all_tasks_match": set(source_tasks) == set(database_tasks) and all(task_checks.values()),
            "all_progress_match": all(progress_checks.values()),
            "migration": self.migration_info(),
        }

    def export_legacy(self, output_dir: str) -> None:
        """Export a database snapshot in the old JSON layout."""
        os.makedirs(output_dir, mode=0o700, exist_ok=True)
        app_data = self.get_app_config() or {}
        app_data["tasks"] = self.list_tasks()
        with open(os.path.join(output_dir, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(app_data, handle, ensure_ascii=False, indent=2)
        progress = {}
        for task_id, item in self.list_progress().items():
            progress[task_id] = {key: item.get(key, default) for key, default in [
                ("task_id", task_id), ("last_message_id", 0),
                ("last_forward_time", ""), ("forwarded_count", 0)
            ]}
        with open(os.path.join(output_dir, "progress.json"), "w", encoding="utf-8") as handle:
            json.dump(progress, handle, ensure_ascii=False, indent=2)
        with open(os.path.join(output_dir, "progress_download.json"), "w", encoding="utf-8") as handle:
            json.dump(self.list_transfers(), handle, ensure_ascii=False, indent=2)
        for task in self.list_tasks():
            with open(os.path.join(output_dir, f"dedup_{task['task_id']}.json"), "w", encoding="utf-8") as handle:
                json.dump({"file_unique_ids": sorted(self.dedup_ids(task["task_id"]))}, handle, ensure_ascii=False, indent=2)
