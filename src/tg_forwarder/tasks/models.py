"""Validated data models shared by Web, CLI and Bot."""
from dataclasses import dataclass, field, asdict, fields
from typing import Optional, List
from datetime import datetime, timezone


@dataclass
class ForwardTask:
    task_id: str
    source_channel: int
    target_channel: int
    min_delay: float
    max_delay: float
    enabled: bool = True
    note: str = ""
    hide_source: bool = True
    caption_prefix: str = ""
    filter_keywords: List[str] = field(default_factory=list)
    required_hashtags: List[str] = field(default_factory=list)
    target_topic_id: Optional[int] = None
    source_topic_id: Optional[int] = None
    remove_hashtags: bool = False
    send_as_channel: bool = False
    deduplicate: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})


@dataclass
class TaskProgress:
    task_id: str
    last_message_id: int = 0
    last_forward_time: str = ""
    forwarded_count: int = 0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def update(self, message_id, count=1):
        self.last_message_id = max(self.last_message_id, message_id)
        self.last_forward_time = datetime.now(timezone.utc).isoformat()
        self.forwarded_count += count


@dataclass
class TaskStatus:
    task_id: str
    status: str
    progress: Optional[TaskProgress] = None
    config: Optional[ForwardTask] = None

    def to_dict(self):
        return {"task_id": self.task_id, "status": self.status,
                "progress": self.progress.to_dict() if self.progress else None,
                "config": self.config.to_dict() if self.config else None}


@dataclass
class ForwardResult:
    success: bool
    method: str
    error: Optional[str] = None
    forwarded_count: int = 0

    def to_dict(self):
        return asdict(self)
