"""Configuration access with record-level optimistic concurrency."""
import os
from copy import deepcopy
from typing import Optional

from .database import Database
from .models import AppConfig, ForwardTask
from .validators import validate_app_config, validate_task


class ConfigManager:
    def __init__(self, config_path="config/config.json", db_path=None):
        self.config_path = config_path
        self.db = Database(db_path or os.path.join(os.path.dirname(config_path), "forwarder.db"))
        self._config: Optional[AppConfig] = None
        self._raw_app = {}
        self._raw_tasks = {}
        self._app_revision = 0
        self._task_revisions = {}

    def load_config(self) -> AppConfig:
        self.db.ensure_legacy_migration(self.config_path)
        # Read values and revisions from the same snapshot.
        with self.db.connection() as db:
            row = db.execute("SELECT data,revision FROM app_settings WHERE id=1").fetchone()
            if not row:
                raise FileNotFoundError(f"Config not found: {self.config_path}")
            import json
            app = json.loads(row["data"])
            self._app_revision = row["revision"]
            tasks = db.execute("SELECT data,revision,task_id FROM tasks ORDER BY task_id").fetchall()
            self._raw_tasks = {row["task_id"]: json.loads(row["data"]) for row in tasks}
            self._task_revisions = {row["task_id"]: row["revision"] for row in tasks}
        self._raw_app = deepcopy(app)
        self._config = AppConfig.from_dict(dict(app, tasks=list(deepcopy(self._raw_tasks).values())))
        return self._config

    def save_app_config(self, config, expected_revision=None):
        config = deepcopy(config)
        validate_app_config(config)
        values = dict(self._raw_app)
        values.update(config.to_dict())
        values.pop("tasks", None)
        self.db.update_app_config(values, self._app_revision if expected_revision is None else expected_revision)
        self.load_config()

    def save_config(self, config):
        """Bootstrap or save changed records; removals require explicit delete."""
        if not self.db.get_app_config():
            values = config.to_dict()
            tasks = values.pop("tasks")
            self.db.save_config(values, tasks)
            self.load_config()
            return
        # Keep detached copies because load_config refreshes the local snapshot.
        app = config.to_dict()
        tasks = app.pop("tasks")
        old_app = AppConfig.from_dict(dict(self._raw_app, tasks=[])).to_dict() if self._raw_app else {}
        old_app.pop("tasks", None)
        revisions = dict(self._task_revisions)
        old_tasks = deepcopy(self._raw_tasks)
        if app != old_app:
            self.save_app_config(config)
        for task in tasks:
            old = old_tasks.get(task["task_id"])
            if old is None or ForwardTask.from_dict(dict(old)).to_dict() != task:
                values = dict(old or {})
                values.update(task)
                self.db.save_task(values, revisions.get(task["task_id"], 0))
        self.load_config()

    def get_config(self):
        return self._config

    def reload(self):
        return self.load_config()

    def add_task(self, task):
        validate_task(task)
        self.db.save_task(task.to_dict(), expected_revision=0)
        self.load_config()

    def remove_task(self, task_id):
        self.db.delete_task(task_id, self._task_revisions.get(task_id, 0))
        self.load_config()

    def update_task(self, task, expected_revision=None, source_reset=None):
        validate_task(task)
        old = self._raw_tasks.get(task.task_id)
        if old is None:
            raise ValueError(f"Task {task.task_id} not found")
        values = dict(old)
        values.update(task.to_dict())
        self.db.save_task(values, self._task_revisions[task.task_id] if expected_revision is None else expected_revision, source_reset)
        self.load_config()

    def get_task(self, task_id):
        return next((task for task in self._config.tasks if task.task_id == task_id), None) if self._config else None

    def create_default_config(self, api_id, api_hash, phone):
        config = AppConfig(api_id=api_id, api_hash=api_hash, phone=phone)
        self.save_config(config)
        return self._config
