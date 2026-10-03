"""Progress and live transfer state backed by SQLite."""
import asyncio
import json
import os
import shutil
import time
from typing import Dict, Optional

from .database import Database
from .models import TaskProgress


class ProgressTracker:
    """Tracks durable checkpoints and live transfer telemetry."""

    def __init__(self, progress_path: str = "config/progress.json", database: Database = None):
        self.progress_path = progress_path
        db_path = os.path.join(os.path.dirname(progress_path), "forwarder.db")
        self.db = database or Database(db_path)
        self._progress: Dict[str, TaskProgress] = {}
        self._download_progress: Dict[str, dict] = {}
        self._transfer_samples: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._download_lock = asyncio.Lock()

    def load_progress(self) -> Dict[str, TaskProgress]:
        self._progress = {}
        for task_id, data in self.db.list_progress().items():
            self._progress[task_id] = TaskProgress(
                task_id=task_id,
                last_message_id=int(data.get("last_message_id", 0)),
                last_forward_time=data.get("last_forward_time", ""),
                forwarded_count=int(data.get("forwarded_count", 0)),
            )
        self._download_progress = self.db.list_transfers()
        return self._progress

    def save_progress(self) -> None:
        for progress in self._progress.values():
            self.db.save_progress(progress.to_dict())

    def get_task_progress(self, task_id: str) -> TaskProgress:
        if task_id not in self._progress:
            self._progress[task_id] = TaskProgress(task_id=task_id)
        return self._progress[task_id]

    def update_progress(self, task_id: str, message_id: int) -> None:
        progress = self.get_task_progress(task_id)
        progress.update(message_id)
        self.db.save_progress(progress.to_dict())

    def advance_progress(self, task_id: str, message_id: int) -> None:
        progress = self.get_task_progress(task_id)
        if message_id > progress.last_message_id:
            progress.last_message_id = message_id
            self.db.save_progress(progress.to_dict())

    def record_forwarded(self, task_id: str, message_id: int, count: int = 1) -> None:
        progress = self.get_task_progress(task_id)
        progress.update(message_id, count)
        self.db.save_progress(progress.to_dict())

    def set_progress(self, task_id: str, last_message_id: int,
                     forwarded_count: Optional[int] = None) -> TaskProgress:
        progress = self.get_task_progress(task_id)
        progress.last_message_id = max(0, int(last_message_id))
        if forwarded_count is not None:
            progress.forwarded_count = max(0, int(forwarded_count))
        progress.last_forward_time = ""
        self.db.save_progress(progress.to_dict())
        return progress

    def reset_progress(self, task_id: str) -> None:
        self._progress[task_id] = TaskProgress(task_id=task_id)
        self.db.save_progress(self._progress[task_id].to_dict())

    def delete_progress(self, task_id: str) -> None:
        self._progress.pop(task_id, None)
        self.db.delete_progress(task_id)

    def get_last_message_id(self, task_id: str) -> int:
        return self.get_task_progress(task_id).last_message_id

    def begin_transfer(self, task_id: str, message_ids: list,
                       total_files: int) -> None:
        """Create a durable snapshot before processing a media group."""
        self.update_transfer(task_id, {
            "type": "group", "state": "fetching",
            "message_ids": [int(value) for value in message_ids],
            "current_message_id": int(message_ids[0]) if message_ids else 0,
            "file_index": 0, "total_files": int(total_files),
            "filename": "", "current": 0, "total": 0,
            "percent": 0, "speed_bps": 0, "speed_str": "等待中",
        })

    def update_transfer(self, task_id: str, data: dict) -> None:
        snapshot = dict(self._download_progress.get(task_id) or self.db.get_transfer(task_id) or {})
        snapshot.update(data)
        snapshot["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._download_progress[task_id] = snapshot
        self.db.save_transfer(task_id, snapshot)

    def get_transfer(self, task_id: str) -> Optional[dict]:
        return self._download_progress.get(task_id) or self.db.get_transfer(task_id)

    def record_error(self, task_id: str, stage: str, error,
                     message_id: int = None, file_index: int = None,
                     filename: str = "", details: str = "") -> None:
        """Persist a transfer failure and keep its context visible after restart."""
        error_text = str(error)
        self.db.add_task_error(
            task_id=task_id,
            stage=stage,
            error=error_text,
            message_id=message_id,
            file_index=file_index,
            filename=filename,
            details=details,
        )
        transfer = self.get_transfer(task_id)
        if transfer:
            snapshot = dict(transfer)
            snapshot.update({
                "state": "error",
                "last_error": error_text,
                "error_stage": stage,
                "error_message_id": message_id,
                "error_file_index": file_index,
                "error_filename": filename or "",
                "error_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            self._download_progress[task_id] = snapshot
            self.db.save_transfer(task_id, snapshot)
        self.db.log_operation(
            "transfer_error", task_id=task_id, result="failed", error=error_text,
            after_data={
                "stage": stage, "message_id": message_id,
                "file_index": file_index, "filename": filename or "",
            },
        )

    def get_task_error_summary(self, task_id: str) -> dict:
        return self.db.task_error_summary(task_id)

    def get_task_errors(self, task_id: str, limit: int = 100) -> list:
        return self.db.list_task_errors(task_id, limit)

    def clear_task_errors(self, task_id: str) -> None:
        self.db.clear_task_errors(task_id)
        self.db.log_operation("clear_task_errors", task_id=task_id)

    def resolve_task_errors(self, task_id: str) -> None:
        self.db.resolve_task_errors(task_id)

    def get_all_transfers(self) -> Dict[str, dict]:
        return dict(self._download_progress or self.db.list_transfers())

    def mark_transfer_state(self, task_id: str, state: str) -> None:
        transfer = self.get_transfer(task_id)
        if transfer:
            if state == "interrupted" and transfer.get("state") == "error":
                return
            transfer["state"] = state
            self.update_transfer(task_id, transfer)

    def clear_transfer(self, task_id: str) -> None:
        self._download_progress.pop(task_id, None)
        self._clear_transfer_sample(task_id)
        self.db.delete_transfer(task_id)

    def _get_transfer_speed(self, task_id: str, transfer_type: str, current: int) -> float:
        now = time.monotonic()
        previous = self._transfer_samples.get(task_id)
        self._transfer_samples[task_id] = {"type": transfer_type, "current": current, "at": now}
        if not previous or previous["type"] != transfer_type:
            return 0.0
        elapsed = now - previous["at"]
        if elapsed <= 0 or current < previous["current"]:
            return 0.0
        return (current - previous["current"]) / elapsed

    def _clear_transfer_sample(self, task_id: str) -> None:
        self._transfer_samples.pop(task_id, None)

    def update_download_progress(self, task_id: str, current: int, total: int,
                                 filename: str = "", message_id: int = 0,
                                 file_index: int = 1, total_files: int = 1) -> None:
        speed = self._get_transfer_speed(task_id, "download", current)
        self.update_transfer(task_id, {
            "type": "download", "state": "downloading", "current": current,
            "total": total, "percent": int(current * 100 / total) if total else 0,
            "filename": filename, "message_id": message_id,
            "current_message_id": message_id, "file_index": file_index,
            "total_files": total_files, "speed_bps": round(speed, 1),
            "speed_str": self._format_speed(speed),
            "forwarded_count": self.get_task_progress(task_id).forwarded_count + 1,
            "current_str": self._format_size(current), "total_str": self._format_size(total),
        })

    def update_upload_progress(self, task_id: str, current: int, total: int,
                               filename: str = "", file_index: int = 1,
                               total_files: int = 1) -> None:
        speed = self._get_transfer_speed(task_id, "upload", current)
        self.update_transfer(task_id, {
            "type": "upload", "state": "uploading", "current": current,
            "total": total, "percent": int(current * 100 / total) if total else 0,
            "filename": filename, "file_index": file_index, "total_files": total_files,
            "speed_bps": round(speed, 1), "speed_str": self._format_speed(speed),
            "forwarded_count": self.get_task_progress(task_id).forwarded_count + 1,
            "current_str": self._format_size(current), "total_str": self._format_size(total),
        })

    def clear_upload_progress(self, task_id: str) -> None:
        transfer = self.get_transfer(task_id)
        if transfer and transfer.get("type") == "upload":
            self.clear_transfer(task_id)

    def clear_download_progress(self, task_id: str) -> None:
        if self.get_transfer(task_id):
            self.clear_transfer(task_id)

    def _format_speed(self, speed_bps: float) -> str:
        if speed_bps <= 0:
            return "计算中"
        if speed_bps < 1024 * 1024:
            return f"{speed_bps / 1024:.1f} KB/s"
        return f"{speed_bps / (1024 * 1024):.1f} MB/s"

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes}B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"
