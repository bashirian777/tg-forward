"""Task manager for Telegram Forwarder."""
import logging
import asyncio
from functools import wraps
from typing import Dict, List, Optional

from tg_forwarder.telegram.client import TelegramClientWrapper
from tg_forwarder.forwarding.handler import MessageHandler
from tg_forwarder.storage.progress_store import ProgressTracker
from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.forwarding.engine import Forwarder
from tg_forwarder.storage.dedup_store import DedupTracker
from .models import ForwardTask, TaskStatus, TaskProgress
from .validation import validate_task, validate_source_reset
from .settings import RuntimeSettings
from .queries import ManagementQueries
from .errors import OperationError, TaskNotFound
from tg_forwarder.storage.workspace import WorkspaceStore


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
                 temp_dir: str = "temp"):
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
        self.client.download_workers = getattr(config, "download_workers", 4)
        self.client.upload_workers = getattr(config, "upload_workers", 4)
        # Fallback chains (hide-source copy) run in parallel up to the
        # media-group limit. Each chain reserves disk for its own file only,
        # so raise min_free_disk_mb when several chains share one disk.
        self.client.disk_semaphore = asyncio.Semaphore(max(1, int(max_concurrent_tasks)))

        self._forwarders: Dict[str, Forwarder] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._statuses: Dict[str, str] = {}  # task_id -> status
        self._operation_locks = {}
        self._settings_lock = asyncio.Lock()
        self._settings = RuntimeSettings(config_manager)
        self._queries = ManagementQueries(config_manager, progress_tracker,
            self.get_task_status, self._dedup_trackers, self._settings)

    def require_task(self, task_id):
        task = self.config_manager.get_task(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        return task

    def is_active(self, task_id):
        task = self._tasks.get(task_id)
        return bool(task and not task.done())

    def create_task(self, task, start_id=0):
        validate_task(task)
        if type(start_id) is not int or start_id < 0:
            raise ValueError("起始消息 ID 必须是非负整数")
        self.config_manager.add_task(task, start_id=start_id)
        self.progress_tracker.load_progress()
        self.config_manager.db.log_operation("create_task", task_id=task.task_id, after_data=task.to_dict())

    def task_snapshot(self, task_id):
        return self._queries.task_snapshot(task_id)

    def task_snapshots(self):
        return self._queries.task_snapshots()

    def config_snapshot(self):
        return self._queries.config_snapshot()

    async def update_settings(self, data):
        async with self._settings_lock:
            candidate, changed = self._settings.prepare_update(data)
            if changed and self.has_running_tasks():
                raise OperationError("stop_all_tasks_before_editing_config", "请先停止全部任务再修改传输参数")
            self._settings.persist(candidate, data.get("revision"))
            if changed:
                self.refresh_runtime_limits()
            self._settings.log_update(candidate)
            return self.config_snapshot()

    async def reload_runtime(self):
        async with self._settings_lock:
            if self.has_running_tasks():
                raise OperationError("stop_all_tasks_before_reload", "请先停止全部任务再重载配置")
            self.config_manager.reload()
            self.progress_tracker.load_progress()
            self._dedup_trackers.clear()
            self.refresh_runtime_limits()

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
        async with self._settings_lock:
            await self._start_task(task_id)

    async def _start_task(self, task_id: str) -> None:
        """Start with the operation and settings locks already held."""
        if task_id in self._tasks and not self._tasks[task_id].done():
            logger.warning(f"Task {task_id} is already running")
            return

        task_config = self.require_task(task_id)
        validate_task(task_config)
        if not task_config.enabled:
            raise OperationError("task_disabled", "Enable the task before starting it", 409)

        await self.client.ensure_ready()

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
            min_free_disk_mb=self.min_free_disk_mb,
            progress_tracker=self.progress_tracker,
            workspace_store=WorkspaceStore(self.temp_dir)
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
        self.config_manager.db.log_operation("start_task", task_id=task_id)
        logger.info(f"Started task {task_id}")

    @serialized_action
    async def pause_task(self, task_id: str) -> None:
        """Pause a running task."""
        if task_id not in self._tasks or self._tasks[task_id].done():
            raise OperationError("task_not_running", "Only a running task can be paused", 409)

        self._forwarders[task_id].pause()
        self._statuses[task_id] = "paused"
        self.config_manager.db.log_operation("pause_task", task_id=task_id)
        logger.info(f"Paused task {task_id}")

    @serialized_action
    async def resume_task(self, task_id: str) -> None:
        """Resume a paused task."""
        if task_id not in self._tasks or self._tasks[task_id].done() or not self._forwarders[task_id].is_paused:
            raise OperationError("task_not_paused", "Only a paused task can be resumed; start stopped tasks", 409)

        self._forwarders[task_id].resume()
        self._statuses[task_id] = "running"
        self.config_manager.db.log_operation("resume_task", task_id=task_id)
        logger.info(f"Resumed task {task_id}")

    @serialized_action
    async def stop_task(self, task_id: str) -> None:
        self.require_task(task_id)
        await self._stop_task(task_id)

    async def _stop_task(self, task_id: str) -> None:
        """Stop with the operation lock held and preserve resumable state."""
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
            except Exception:
                logger.exception("Task %s exited with an error", task_id)

        # Flush dedup records to disk
        if task_id in self._dedup_trackers:
            self._dedup_trackers[task_id].flush()

        self._statuses[task_id] = "stopped"
        self.config_manager.db.log_operation("stop_task", task_id=task_id)
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
        return self._queries.list_tasks()

    def has_running_tasks(self) -> bool:
        return any(task and not task.done() for task in self._tasks.values())

    def refresh_runtime_limits(self) -> None:
        config = self.config_manager.get_config()
        if not config:
            return
        self.temp_dir = getattr(config, "temp_dir", self.temp_dir) or self.temp_dir
        self.min_free_disk_mb = max(0, int(getattr(config, "min_free_disk_mb", self.min_free_disk_mb)))
        groups = max(1, int(getattr(config, "max_concurrent_tasks", 1)))
        self._group_semaphore = asyncio.Semaphore(groups)
        self.client.download_workers = config.download_workers
        self.client.upload_workers = config.upload_workers
        self.client.disk_semaphore = asyncio.Semaphore(groups)

    def update_task(self, task: ForwardTask, expected_revision=None, source_reset=None) -> None:
        """Update a task configuration; running tasks must be stopped first."""
        if task.task_id in self._tasks and not self._tasks[task.task_id].done():
            raise OperationError("task_active", "Stop the task before editing its configuration", 409)
        old = self.require_task(task.task_id)
        # A stale form must reload before source-change semantics are evaluated.
        self.config_manager.check_task_revision(task.task_id, expected_revision)
        source_changed = validate_source_reset(old.to_dict(), task.to_dict(), source_reset)
        self.config_manager.update_task(task, expected_revision, source_reset if source_changed else None)
        if source_changed:
            self.cleanup_files(task.task_id)
            self.progress_tracker.load_progress()
            self._dedup_trackers.pop(task.task_id, None)
        self.config_manager.db.log_operation(
            "update_task", task_id=task.task_id, after_data=task.to_dict()
        )

    def set_progress(self, task_id: str, last_message_id: int,
                     forwarded_count: Optional[int] = None) -> TaskProgress:
        """Set a checkpoint; callers must stop the task before using it."""
        if task_id in self._tasks and not self._tasks[task_id].done():
            raise OperationError("task_active", "Stop the task before editing progress", 409)
        self.require_task(task_id)
        if type(last_message_id) is not int or last_message_id < 0:
            raise ValueError("Checkpoint must be a nonnegative integer")
        if forwarded_count is not None and (type(forwarded_count) is not int or forwarded_count < 0):
            raise ValueError("Forwarded count must be a nonnegative integer")
        count = self.progress_tracker.get_task_progress(task_id).forwarded_count if forwarded_count is None else forwarded_count
        progress = self.progress_tracker.replace_checkpoint(task_id, last_message_id, count)
        self.config_manager.db.log_operation(
            "set_progress", task_id=task_id, after_data=progress.to_dict()
        )
        return progress

    def get_transfer(self, task_id: str) -> Optional[dict]:
        return self._queries.get_transfer(task_id)

    def get_all_transfers(self):
        return self._queries.get_all_transfers()

    def progress_snapshot(self, task_id):
        return self._queries.progress_snapshot(task_id)

    def dedup_snapshot(self, task_id, limit=500):
        return self._queries.dedup_snapshot(task_id, limit)

    def errors_snapshot(self, task_id, limit=100):
        return self._queries.errors_snapshot(task_id, limit)

    def get_logs(self, limit=100):
        return self._queries.get_logs(limit)

    def system_snapshot(self, started_at):
        return self._queries.system_snapshot(started_at)

    def cleanup_files(self, task_id=None, expired_only=False):
        config = self.config_manager.get_config()
        return WorkspaceStore(self.temp_dir).cleanup(task_id=task_id,
            max_age_hours=config.temp_max_age_hours if expired_only else None)

    @serialized_action
    async def cleanup_task_files(self, task_id):
        self.require_task(task_id)
        await self._stop_task(task_id)
        result = self.cleanup_files(task_id)
        self.progress_tracker.clear_transfer(task_id)
        self.config_manager.db.log_operation("cleanup_files", task_id=task_id, after_data=result)
        return result

    @serialized_action
    async def retry_transfer(self, task_id):
        self.require_task(task_id)
        was_active = self.is_active(task_id)
        was_paused = was_active and self._forwarders[task_id].is_paused
        await self._stop_task(task_id)
        self.clear_transfer(task_id)
        if was_active:
            async with self._settings_lock:
                await self._start_task(task_id)
                if was_paused:
                    self._forwarders[task_id].pause()
                    self._statuses[task_id] = "paused"
        return {"resume_from": self.progress_tracker.get_last_message_id(task_id), "restarted": was_active}

    @serialized_action
    async def skip_current_transfer(self, task_id):
        self.require_task(task_id)
        await self._stop_task(task_id)
        return {"skipped_through": self.skip_transfer(task_id)}

    @serialized_action
    async def edit_task(self, task_id, task, revision=None, source_reset=None):
        self.update_task(task, revision, source_reset)
        return self.task_snapshot(task_id)

    @serialized_action
    async def edit_progress(self, task_id, last_message_id, forwarded_count=None):
        return self.set_progress(task_id, last_message_id, forwarded_count).to_dict()

    @serialized_action
    async def reset_dedup(self, task_id):
        self.require_task(task_id)
        if self.is_active(task_id):
            raise OperationError("stop_task_before_clearing_dedup", "请先停止任务再清空去重记录")
        self.clear_dedup(task_id)

    @serialized_action
    async def reset_errors(self, task_id):
        self.require_task(task_id)
        self.clear_task_errors(task_id)
        transfer = self.get_transfer(task_id)
        if transfer and transfer.get("state") == "error" and not self.is_active(task_id):
            self.progress_tracker.mark_transfer_state(task_id, "interrupted")

    def clear_transfer(self, task_id: str) -> None:
        self.cleanup_files(task_id)
        self.progress_tracker.clear_transfer(task_id)
        self.config_manager.db.log_operation("clear_transfer", task_id=task_id)

    def skip_transfer(self, task_id: str) -> int:
        """Skip only this group, retaining pending interleaved source messages."""
        transfer = self.progress_tracker.get_transfer(task_id)
        if not transfer:
            raise OperationError("transfer_missing", "No active transfer for this task", 409)
        message_ids = [int(value) for value in transfer.get("message_ids", [])]
        if not message_ids:
            raise ValueError("Active transfer has no message IDs")
        self.progress_tracker.complete_group(task_id, message_ids, "explicit_skip", 0,
            transfer.get("ordered_ids") or message_ids)
        checkpoint = self.progress_tracker.get_last_message_id(task_id)
        self.cleanup_files(task_id)
        self.progress_tracker.clear_transfer(task_id)
        self.config_manager.db.log_operation(
            "skip_transfer", task_id=task_id,
            after_data={"skipped_message_ids": message_ids, "new_last_message_id": checkpoint}
        )
        return checkpoint


    def get_dedup_stats(self, task_id: str) -> dict:
        return self._queries.get_dedup_stats(task_id)

    def clear_dedup(self, task_id: str) -> None:
        if task_id in self._dedup_trackers:
            self._dedup_trackers[task_id].clear()
        else:
            self.config_manager.db.clear_dedup(task_id)
        self.config_manager.db.log_operation("clear_dedup", task_id=task_id)

    def get_task_error_summary(self, task_id: str) -> dict:
        return self._queries.get_task_error_summary(task_id)

    def get_task_errors(self, task_id: str, limit: int = 100) -> list:
        return self._queries.get_task_errors(task_id, limit)

    def clear_task_errors(self, task_id: str) -> None:
        self.progress_tracker.clear_task_errors(task_id)

    @serialized_action
    async def delete_task(self, task_id: str) -> None:
        """Stop and remove configuration, child rows, files and cached state."""
        self.require_task(task_id)
        await self._stop_task(task_id)
        self.cleanup_files(task_id)
        self.config_manager.remove_task(task_id)
        self.progress_tracker.forget_task(task_id)
        self._dedup_trackers.pop(task_id, None)

        # Child progress rows were removed transactionally by the foreign key.
        # Cleanup internal state
        self._forwarders.pop(task_id, None)
        self._tasks.pop(task_id, None)
        self._statuses.pop(task_id, None)

        self.config_manager.db.log_operation("delete_task", task_id=task_id)
        logger.info(f"Deleted task {task_id}")
