"""Deduplication tracker backed by SQLite."""
import logging
from typing import List, Optional

from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument

from .database import Database


logger = logging.getLogger(__name__)


class DedupTracker:
    """Tracks forwarded media IDs in the shared database."""

    def __init__(self, task_id: str, storage_dir: str = "config",
                 save_interval: int = 50, database: Database = None):
        self.task_id = task_id
        self.db = database or Database(f"{storage_dir}/forwarder.db")
        self._file_ids = self.db.dedup_ids(task_id)

    def _get_file_unique_id(self, message: Message) -> Optional[str]:
        if not message.media:
            return None
        try:
            if isinstance(message.media, MessageMediaPhoto) and message.media.photo:
                return f"photo_{message.media.photo.id}"
            if isinstance(message.media, MessageMediaDocument) and message.media.document:
                return f"doc_{message.media.document.id}"
        except Exception as e:
            logger.debug("[%s] Failed to get file id: %s", self.task_id, e)
        return None

    def is_duplicate(self, message: Message) -> bool:
        file_id = self._get_file_unique_id(message)
        return bool(file_id and file_id in self._file_ids)

    def is_group_duplicate(self, messages: List[Message]) -> bool:
        return any(self.is_duplicate(message) for message in messages)

    def mark_as_sent(self, message: Message) -> None:
        file_id = self._get_file_unique_id(message)
        if file_id and file_id not in self._file_ids:
            self._file_ids.add(file_id)
            self.db.add_dedup_ids(self.task_id, [file_id])

    def mark_group_as_sent(self, messages: List[Message]) -> None:
        values = {
            file_id for message in messages
            if (file_id := self._get_file_unique_id(message))
            and file_id not in self._file_ids
        }
        if values:
            self._file_ids.update(values)
            self.db.add_dedup_ids(self.task_id, values)
            logger.info("[%s] Added %s dedup record(s)", self.task_id, len(values))

    def get_stats(self) -> dict:
        return {
            "task_id": self.task_id,
            "total_tracked": self.db.dedup_count(self.task_id),
            "storage_path": self.db.path,
            "pending_saves": 0,
        }

    def clear(self) -> None:
        self._file_ids.clear()
        self.db.clear_dedup(self.task_id)
        logger.info("[%s] Cleared dedup records", self.task_id)

    def flush(self) -> None:
        """Retained for TaskManager compatibility; SQLite writes immediately."""
        return None
