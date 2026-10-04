"""Runtime settings and tasks, with record-level optimistic concurrency."""
import json
from copy import deepcopy
from typing import Optional

from .database import Database
from .models import ForwardTask, RuntimeConfig
from .paths import PROJECT_ROOT
from .validators import validate_runtime_config, validate_task


class ConfigManager:
    def __init__(self, db_path="config/forwarder.db", *, database=None, create=True, project_root=PROJECT_ROOT):
        self.db = database or Database(db_path, create=create)
        self.project_root = project_root
        self._config: Optional[RuntimeConfig] = None
        self._raw_app = {}
        self._raw_tasks = {}
        self._app_revision = 0
        self._task_revisions = {}

    def initialize(self, initial_password=""):
        config = RuntimeConfig(web_password=initial_password)
        validate_runtime_config(config, self.project_root)
        created = self.db.initialize_settings(config.settings_dict())
        self.load_config()
        return created

    def load_config(self) -> RuntimeConfig:
        # Values and their revisions must come from the same snapshot.
        with self.db.connection() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT data,revision FROM app_settings WHERE id=1").fetchone()
            if not row:
                raise FileNotFoundError("Database is not initialized; run 'init'")
            app = json.loads(row["data"])
            revision = row["revision"]
            tasks = db.execute("SELECT data,revision,task_id FROM tasks ORDER BY task_id").fetchall()
            raw_tasks = {row["task_id"]: json.loads(row["data"]) for row in tasks}
            revisions = {row["task_id"]: row["revision"] for row in tasks}
        if set(app) - RuntimeConfig.setting_names():
            raise ValueError("Database still contains deployment settings; run 'migrate-env'")
        config = RuntimeConfig.from_dict(dict(app, tasks=list(raw_tasks.values())))
        validate_runtime_config(config, self.project_root)
        self._app_revision = revision
        self._raw_app, self._raw_tasks = app, raw_tasks
        self._task_revisions, self._config = revisions, config
        return config

    def save_app_config(self, config: RuntimeConfig, expected_revision=None):
        if type(config) is not RuntimeConfig:
            raise TypeError("Expected RuntimeConfig")
        candidate = deepcopy(config)
        validate_runtime_config(candidate, self.project_root)
        self.db.update_app_config(candidate.settings_dict(),
            self._app_revision if expected_revision is None else expected_revision)
        self.load_config()

    def save_config(self, config: RuntimeConfig):
        """Save changed records; removing tasks requires an explicit delete."""
        if type(config) is not RuntimeConfig:
            raise TypeError("Expected RuntimeConfig")
        candidate = deepcopy(config)
        validate_runtime_config(candidate, self.project_root)
        for task in candidate.tasks:
            validate_task(task)
        if len({task.task_id for task in candidate.tasks}) != len(candidate.tasks):
            raise ValueError("Task IDs must be unique")
        if not self.db.get_app_config():
            self.db.save_config(candidate.settings_dict(), [task.to_dict() for task in candidate.tasks])
            self.load_config()
            return
        revisions, old_tasks = dict(self._task_revisions), deepcopy(self._raw_tasks)
        if candidate.settings_dict() != RuntimeConfig.from_dict(self._raw_app).settings_dict():
            self.save_app_config(candidate)
        for task in candidate.tasks:
            old = old_tasks.get(task.task_id)
            if old is None or ForwardTask.from_dict(old).to_dict() != task.to_dict():
                self.db.save_task(dict(old or {}, **task.to_dict()), revisions.get(task.task_id, 0))
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
        self.db.save_task(dict(old, **task.to_dict()),
            self._task_revisions[task.task_id] if expected_revision is None else expected_revision, source_reset)
        self.load_config()

    def get_task(self, task_id):
        return next((task for task in self._config.tasks if task.task_id == task_id), None) if self._config else None
