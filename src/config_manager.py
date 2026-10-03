"""Configuration access backed by the SQLite repository."""
import os
from typing import Optional

from .database import Database
from .models import AppConfig, ForwardTask


class ConfigManager:
    """Loads and updates application configuration transactionally."""

    def __init__(self, config_path: str = "config/config.json", db_path: str = None):
        self.config_path = config_path
        self.db = Database(db_path or os.path.join(os.path.dirname(config_path), "forwarder.db"))
        self._config: Optional[AppConfig] = None
        self._raw_app = {}
        self._raw_tasks = {}

    def load_config(self) -> AppConfig:
        """Migrate legacy JSON once, then load the database snapshot."""
        self.db.ensure_legacy_migration(self.config_path)
        app_data = self.db.get_app_config()
        if app_data is None:
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        raw_tasks = self.db.list_tasks()
        self._raw_app = dict(app_data)
        self._raw_tasks = {str(task["task_id"]): dict(task) for task in raw_tasks}
        data = dict(app_data)
        data["tasks"] = raw_tasks
        self._config = AppConfig.from_dict(data)
        return self._config

    def save_config(self, config: AppConfig) -> None:
        """Save configuration and tasks in one database transaction."""
        app_data = dict(self._raw_app)
        app_data.update(config.to_dict())
        app_data.pop("tasks", None)

        task_data = []
        for task in config.tasks:
            current = dict(self._raw_tasks.get(task.task_id, {}))
            current.update(task.to_dict())
            task_data.append(current)

        self.db.save_config(app_data, task_data)
        self._raw_app = app_data
        self._raw_tasks = {str(task["task_id"]): dict(task) for task in task_data}
        self._config = config

    def get_config(self) -> Optional[AppConfig]:
        return self._config

    def reload(self) -> AppConfig:
        return self.load_config()

    def add_task(self, task: ForwardTask) -> None:
        if self._config is None:
            raise ValueError("Config not loaded. Call load_config() first.")
        if self.get_task(task.task_id):
            raise ValueError(f"Task with id '{task.task_id}' already exists")
        self._config.tasks.append(task)
        self.save_config(self._config)

    def remove_task(self, task_id: str) -> None:
        if self._config is None:
            raise ValueError("Config not loaded. Call load_config() first.")
        original_count = len(self._config.tasks)
        self._config.tasks = [task for task in self._config.tasks if task.task_id != task_id]
        if len(self._config.tasks) == original_count:
            raise ValueError(f"Task with id '{task_id}' not found")
        self.save_config(self._config)

    def update_task(self, task: ForwardTask) -> None:
        if self._config is None:
            raise ValueError("Config not loaded. Call load_config() first.")
        for index, existing in enumerate(self._config.tasks):
            if existing.task_id == task.task_id:
                self._config.tasks[index] = task
                self.save_config(self._config)
                return
        raise ValueError(f"Task with id '{task.task_id}' not found")

    def get_task(self, task_id: str) -> Optional[ForwardTask]:
        if self._config is None:
            return None
        return next((task for task in self._config.tasks if task.task_id == task_id), None)

    def create_default_config(self, api_id: int, api_hash: str, phone: str) -> AppConfig:
        config = AppConfig(api_id=api_id, api_hash=api_hash, phone=phone, tasks=[])
        self.save_config(config)
        return config
