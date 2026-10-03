"""Task manager for Telegram Forwarder."""
import logging
import asyncio
from functools import wraps
from typing import Dict, List, Optional

from .telegram_client import TelegramClientWrapper
from .message_handler import MessageHandler
from .progress_tracker import ProgressTracker
from .config_manager import ConfigManager
from .forwarder import Forwarder
from .dedup_tracker import DedupTracker
from .models import ForwardTask, TaskStatus, TaskProgress
from .validators import validate_task
from .workspace import WorkspaceStore


logger = logging.getLogger(__name__)


def serialized_action(method):
    @wraps(method)
    async def wrapped(self, task_id, *args, **kwargs):
        async with self._operation_locks.setdefault(task_id, asyncio.Lock()):
            return await method(self, task_id, *args, **kwargs)
    return wrapped


class TaskManager:
    """Manages multiple forwarding tasks concurrently."""

    def __init__(self, client: TelegramClientWrapper,
                 config_manager: ConfigManager,
                 progress_tracker: ProgressTracker,
                 temp_dir: str = "temp",
                 bot_client=None):
        self.client = client
        self.config_manager = config_manager
        self.progress_tracker = progress_tracker
        self.temp_dir = temp_dir
        config = self.config_manager.get_config()
        max_concurrent_tasks = getattr(config, "max_concurrent_tasks", 1) if config else 1
        self._group_semaphore = asyncio.Semaphore(max(1, int(max_concurrent_tasks)))
        min_free_disk_mb = getattr(config, "min_free_disk_mb", 1024) if config else 1024
        self.min_free_disk_mb = max(0, int(min_free_disk_mb))
        self._dedup_trackers: Dict[str, DedupTracker] = {}  # Per-task dedup trackers

        # Set progress tracker on client for progress updates
        self.client.set_progress_tracker(progress_tracker)

        self._forwarders: Dict[str, Forwarder] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._statuses: Dict[str, str] = {}  # task_id -> status
        self._operation_locks = {}

    async def start_all_tasks(self) -> None:
        """Start all enabled tasks from configuration."""
        config = self.config_manager.get_config()
        if config is None:
            raise ValueError("Config not loaded")

        for task in config.tasks:
            if task.enabled:
                await self.start_task(task.task_id)

    @serialized_action
    async def start_task(self, task_id: str) -> None:
        """Start a specific task by ID."""
        if task_id in self._tasks and not self._tasks[task_id].done():
            logger.warning(f"Task {task_id} is already running")
            return

        task_config = self.config_manager.get_task(task_id)
        if task_config is None:
            raise ValueError(f"Task {task_id} not found in configuration")
        validate_task(task_config)
        if not task_config.enabled:
            raise ValueError("Enable the task before starting it")

        # Create forwarder for this task with its own dedup tracker
        dedup_tracker = None
        if task_config.deduplicate:
            if task_id not in self._dedup_trackers:
                self._dedup_trackers[task_id] = DedupTracker(
                    task_id, database=self.config_manager.db
                )
            dedup_tracker = self._dedup_trackers[task_id]

        message_handler = MessageHandler(
            self.client,
            self.temp_dir,
            dedup_tracker=dedup_tracker,
            min_free_disk_mb=self.min_free_disk_mb
        )
        forwarder = Forwarder(
            self.client,
            message_handler,
            self.progress_tracker,
            group_semaphore=self._group_semaphore
        )
        self._forwarders[task_id] = forwarder

        # Start task
        self._tasks[task_id] = asyncio.create_task(
            forwarder.run_task(task_config)
        )
        self._statuses[task_id] = "running"
        logger.info(f"Started task {task_id}")

    @serialized_action
    async def pause_task(self, task_id: str) -> None:
        """Pause a running task."""
        if task_id not in self._tasks or self._tasks[task_id].done():
            raise ValueError("Only a running task can be paused")

        self._forwarders[task_id].pause()
        self._statuses[task_id] = "paused"
        logger.info(f"Paused task {task_id}")

    @serialized_action
    async def resume_task(self, task_id: str) -> None:
        """Resume a paused task."""
        if task_id not in self._tasks or self._tasks[task_id].done() or not self._forwarders[task_id].is_paused:
            raise ValueError("Only a paused task can be resumed; start stopped tasks")

        self._forwarders[task_id].resume()
        self._statuses[task_id] = "running"
        logger.info(f"Resumed task {task_id}")

    @serialized_action
    async def stop_task(self, task_id: str) -> None:
        """Stop a specific task and preserve any active transfer as interrupted."""
        if task_id in self._forwarders:
            self._forwarders[task_id].stop()

        if self.progress_tracker.get_transfer(task_id):
            self.progress_tracker.mark_transfer_state(task_id, "interrupted")

        if task_id in self._tasks:
            self._tasks[task_id].cancel()
            try:
                await self._tasks[task_id]
            except asyncio.CancelledError:
                pass

        # Flush dedup records to disk
        if task_id in self._dedup_trackers:
            self._dedup_trackers[task_id].flush()

        self._statuses[task_id] = "stopped"
        logger.info(f"Stopped task {task_id}")

    async def stop_all_tasks(self) -> None:
        """Stop all running tasks."""
        for task_id in list(self._tasks.keys()):
            await self.stop_task(task_id)

    def get_task_status(self, task_id: str) -> TaskStatus:
        """Get status of a specific task."""
        task_config = self.config_manager.get_task(task_id)
        progress = self.progress_tracker.get_task_progress(task_id)
        status = self._statuses.get(task_id, "stopped")
        runtime = self._tasks.get(task_id)
        forwarder = self._forwarders.get(task_id)
        if runtime and runtime.done():
            status = "error" if forwarder and forwarder.error else "stopped"
        elif runtime:
            status = "paused" if forwarder.is_paused else "running"

        return TaskStatus(
            task_id=task_id,
            status=status,
            progress=progress,
            config=task_config
        )

    def list_tasks(self) -> List[TaskStatus]:
        """List all tasks with their status."""
        config = self.config_manager.get_config()
        if config is None:
            return []

        return [self.get_task_status(task.task_id) for task in config.tasks]

    def has_running_tasks(self) -> bool:
        return any(task and not task.done() for task in self._tasks.values())

    def refresh_runtime_limits(self) -> None:
        config = self.config_manager.get_config()
        if not config:
            return
        self.temp_dir = getattr(config, "temp_dir", self.temp_dir) or self.temp_dir
        self.min_free_disk_mb = max(0, int(getattr(config, "min_free_disk_mb", self.min_free_disk_mb)))
        self._group_semaphore = asyncio.Semaphore(max(1, int(getattr(config, "max_concurrent_tasks", 1))))

    def update_task(self, task: ForwardTask, expected_revision=None, source_reset=None) -> None:
        """Update a task configuration; running tasks must be stopped first."""
        if task.task_id in self._tasks and not self._tasks[task.task_id].done():
            raise ValueError("Stop the task before editing its configuration")
        old = self.config_manager.get_task(task.task_id)
        source_changed = old and (old.source_channel, old.source_topic_id) != (task.source_channel, task.source_topic_id)
        if source_changed and (not isinstance(source_reset, dict) or "last_message_id" not in source_reset or type(source_reset.get("clear_dedup")) is not bool):
            raise ValueError("Changing source requires source_reset with last_message_id and clear_dedup")
        if source_changed:
            if type(source_reset["last_message_id"]) is not int or source_reset["last_message_id"] < 0:
                raise ValueError("New source checkpoint must be a nonnegative integer")
        self.config_manager.update_task(task, expected_revision, source_reset if source_changed else None)
        if source_changed:
            self.progress_tracker.load_progress()
            self._dedup_trackers.pop(task.task_id, None)
        self.config_manager.db.log_operation(
            "update_task", task_id=task.task_id, after_data=task.to_dict()
        )

    def set_progress(self, task_id: str, last_message_id: int,
                     forwarded_count: Optional[int] = None) -> TaskProgress:
        """Set a checkpoint; callers must stop the task before using it."""
        if task_id in self._tasks and not self._tasks[task_id].done():
            raise ValueError("Stop the task before editing progress")
        if not self.config_manager.get_task(task_id):
            raise ValueError("Task not found")
        if type(last_message_id) is not int or last_message_id < 0:
            raise ValueError("Checkpoint must be a nonnegative integer")
        if forwarded_count is not None and (type(forwarded_count) is not int or forwarded_count < 0):
            raise ValueError("Forwarded count must be a nonnegative integer")
        count = self.progress_tracker.get_task_progress(task_id).forwarded_count if forwarded_count is None else forwarded_count
        self.progress_tracker.reset_task_state(task_id)
        progress = self.progress_tracker.set_progress(task_id, last_message_id, count)
        self.config_manager.db.log_operation(
            "set_progress", task_id=task_id, after_data=progress.to_dict()
        )
        return progress

    def get_transfer(self, task_id: str) -> Optional[dict]:
        return self.progress_tracker.get_transfer(task_id)

    def cleanup_files(self, task_id=None, expired_only=False):
        config = self.config_manager.get_config()
        return WorkspaceStore(self.temp_dir).cleanup(task_id=task_id,
            max_age_hours=config.temp_max_age_hours if expired_only else None)

    async def cleanup_task_files(self, task_id):
        await self.stop_task(task_id)
        result = self.cleanup_files(task_id)
        self.progress_tracker.clear_transfer(task_id)
        self.config_manager.db.log_operation("cleanup_files", task_id=task_id, after_data=result)
        return result

    def clear_transfer(self, task_id: str) -> None:
        self.cleanup_files(task_id)
        self.progress_tracker.clear_transfer(task_id)
        self.config_manager.db.log_operation("clear_transfer", task_id=task_id)

    def skip_transfer(self, task_id: str) -> int:
        """Explicitly skip the interrupted group and advance past its highest ID."""
        transfer = self.progress_tracker.get_transfer(task_id)
        if not transfer:
            raise ValueError("No active transfer for this task")
        message_ids = [int(value) for value in transfer.get("message_ids", [])]
        if not message_ids:
            raise ValueError("Active transfer has no message IDs")
        highest_id = max(message_ids)
        progress = self.progress_tracker.get_task_progress(task_id)
        self.progress_tracker.set_progress(task_id, highest_id, progress.forwarded_count)
        self.cleanup_files(task_id)
        self.progress_tracker.clear_transfer(task_id)
        self.config_manager.db.log_operation(
            "skip_transfer", task_id=task_id,
            after_data={"skipped_message_ids": message_ids, "new_last_message_id": highest_id}
        )
        return highest_id


    def get_dedup_stats(self, task_id: str) -> dict:
        tracker = self._dedup_trackers.get(task_id)
        if tracker:
            return tracker.get_stats()
        return {
            "task_id": task_id,
            "total_tracked": self.config_manager.db.dedup_count(task_id),
            "storage_path": self.config_manager.db.path,
            "pending_saves": 0,
        }

    def clear_dedup(self, task_id: str) -> None:
        if task_id in self._dedup_trackers:
            self._dedup_trackers[task_id].clear()
        else:
            self.config_manager.db.clear_dedup(task_id)
        self.config_manager.db.log_operation("clear_dedup", task_id=task_id)

    def get_task_error_summary(self, task_id: str) -> dict:
        return self.progress_tracker.get_task_error_summary(task_id)

    def get_task_errors(self, task_id: str, limit: int = 100) -> list:
        return self.progress_tracker.get_task_errors(task_id, limit)

    def clear_task_errors(self, task_id: str) -> None:
        self.progress_tracker.clear_task_errors(task_id)

    async def delete_task(self, task_id: str, delete_progress: bool = False) -> None:
        """Delete a task from configuration."""
        # Stop if running
        if task_id in self._tasks:
            await self.stop_task(task_id)

        self.cleanup_files(task_id)
        # Remove from config
        self.config_manager.remove_task(task_id)
        self.progress_tracker._download_progress.pop(task_id, None)
        self._dedup_trackers.pop(task_id, None)

        # Optionally remove progress
        if delete_progress:
            self.progress_tracker.delete_progress(task_id)

        # Cleanup internal state
        self._forwarders.pop(task_id, None)
        self._tasks.pop(task_id, None)
        self._statuses.pop(task_id, None)

        self.config_manager.db.log_operation("delete_task", task_id=task_id)
        logger.info(f"Deleted task {task_id}")
