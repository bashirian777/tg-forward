"""Assemble management reads without exposing live transfer or config state."""
from copy import deepcopy
from datetime import datetime, timezone
import os
import shutil
import time

from tg_forwarder.storage.workspace import WorkspaceStore
from .errors import TaskNotFound


class ManagementQueries:
    def __init__(self, config_manager, progress_tracker, status_getter,
                 dedup_trackers, settings):
        self.config_manager = config_manager
        self.progress_tracker = progress_tracker
        self.status_getter = status_getter
        self.dedup_trackers = dedup_trackers
        self.settings = settings

    def list_tasks(self):
        config = self.config_manager.get_config()
        if config is None:
            return []
        return [self.status_getter(task.task_id) for task in config.tasks]

    def task_snapshot(self, task_id):
        if self.config_manager.get_task(task_id) is None:
            raise TaskNotFound(task_id)
        status = self.status_getter(task_id)
        return deepcopy(dict(status.to_dict(),
            transfer=self.get_transfer(task_id), dedup=self.get_dedup_stats(task_id),
            errors=self.get_task_error_summary(task_id),
            revision=self.config_manager.task_revision(task_id)))

    def task_sort_mode(self):
        return self.config_manager.db.get_metadata("task_sort_mode") or "manual"

    def task_snapshots(self, sort_mode=None):
        tasks = [self.task_snapshot(task.task_id) for task in self.list_tasks()]
        if (sort_mode or self.task_sort_mode()) == "recent":
            def last_forward(task):
                value = task["progress"]["last_forward_time"]
                if not value:
                    return float("-inf")
                try:
                    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return timestamp.replace(tzinfo=timezone.utc).timestamp() if timestamp.tzinfo is None else timestamp.timestamp()
                except (ValueError, TypeError, OverflowError):
                    return float("-inf")
            tasks.sort(key=last_forward, reverse=True)
        return tasks

    def tasks_view(self):
        mode = self.task_sort_mode()
        return {"tasks": self.task_snapshots(mode), "sort_mode": mode}

    def config_snapshot(self):
        return self.settings.snapshot()

    def progress_snapshot(self, task_id):
        return deepcopy(self.progress_tracker.get_task_progress(task_id).to_dict())

    def get_transfer(self, task_id):
        return deepcopy(self.progress_tracker.get_transfer(task_id))

    def get_all_transfers(self):
        return deepcopy(self.progress_tracker.get_all_transfers())

    def get_dedup_stats(self, task_id):
        tracker = self.dedup_trackers.get(task_id)
        if tracker:
            return deepcopy(tracker.get_stats())
        return {
            "task_id": task_id,
            "total_tracked": self.config_manager.db.dedup_count(task_id),
            "storage_path": self.config_manager.db.path,
            "pending_saves": 0,
        }

    def dedup_snapshot(self, task_id, limit=500):
        return {"stats": self.get_dedup_stats(task_id),
            "records": deepcopy(self.config_manager.db.list_dedup(task_id, limit))}

    def get_task_error_summary(self, task_id):
        return deepcopy(self.progress_tracker.get_task_error_summary(task_id))

    def get_task_errors(self, task_id, limit=100):
        return deepcopy(self.progress_tracker.get_task_errors(task_id, limit))

    def errors_snapshot(self, task_id, limit=100):
        return {"summary": self.get_task_error_summary(task_id),
            "errors": self.get_task_errors(task_id, limit)}

    def get_logs(self, limit=100):
        return deepcopy(self.config_manager.db.list_logs(limit))

    def system_snapshot(self, started_at):
        config = self.config_manager.get_config()
        root = shutil.disk_usage("/")
        exists = os.path.isdir(config.temp_dir)
        temp = shutil.disk_usage(config.temp_dir) if exists else None

        def disk(usage):
            return {"total": usage.total, "used": usage.used, "free": usage.free,
                "percent": round(usage.used * 100 / usage.total, 1)} if usage else None

        return {"disk": disk(root), "temp_disk": disk(temp), "temp_dir": config.temp_dir,
            "temp_exists": exists, "temp_files": WorkspaceStore(config.temp_dir).stats(),
            "uptime_seconds": int(time.monotonic() - started_at),
            "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else []}
