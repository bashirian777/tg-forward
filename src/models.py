"""Data models for Telegram Forwarder."""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class ForwardTask:
    """Configuration for a single forwarding task."""
    task_id: str
    source_channel: int
    target_channel: int
    min_delay: float  # Minimum delay in seconds
    max_delay: float  # Maximum delay in seconds
    enabled: bool = True
    note: str = ""  # 任务备注
    hide_source: bool = True  # 隐藏来源（不显示"转发自"）
    caption_prefix: str = ""  # 转发时添加到描述文本前面的前缀
    filter_keywords: List[str] = field(default_factory=list)  # 过滤关键词列表（包含则跳过）
    required_hashtags: List[str] = field(default_factory=list)  # 必须包含的hashtag列表（必须包含其中之一才转发）
    target_topic_id: Optional[int] = None  # 目标群组的话题ID（用于论坛群组）
    source_topic_id: Optional[int] = None  # 源论坛群组话题ID，只处理该话题消息
    remove_hashtags: bool = False  # 转发后是否删除required_hashtags中的hashtag
    send_as_channel: bool = False  # 以目标频道/群组身份发送（需要是管理员）
    deduplicate: bool = False  # 是否启用去重（基于file_unique_id）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ForwardTask":
        # Handle old configs without new fields
        if "note" not in data:
            data["note"] = ""
        if "hide_source" not in data:
            data["hide_source"] = True
        if "caption_prefix" not in data:
            data["caption_prefix"] = ""
        if "filter_keywords" not in data:
            data["filter_keywords"] = []
        if "required_hashtags" not in data:
            data["required_hashtags"] = []
        if "target_topic_id" not in data:
            data["target_topic_id"] = None
        if "source_topic_id" not in data:
            data["source_topic_id"] = None
        if "remove_hashtags" not in data:
            data["remove_hashtags"] = False
        if "send_as_channel" not in data:
            data["send_as_channel"] = False
        if "deduplicate" not in data:
            data["deduplicate"] = False
        return cls(**data)


@dataclass
class TaskProgress:
    """Progress tracking for a forwarding task."""
    task_id: str
    last_message_id: int = 0
    last_forward_time: str = ""  # ISO format timestamp
    forwarded_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskProgress":
        return cls(**data)

    def update(self, message_id: int, count: int = 1) -> None:
        """Update progress with new message ID and forwarded message count."""
        self.last_message_id = message_id
        self.last_forward_time = datetime.utcnow().isoformat() + "Z"
        self.forwarded_count += count


@dataclass
class AppConfig:
    """Application configuration."""
    api_id: int
    api_hash: str
    phone: str
    bot_token: str = ""  # Bot token for management bot
    admin_ids: List[int] = field(default_factory=list)  # Admin user IDs
    tasks: List[ForwardTask] = field(default_factory=list)
    temp_dir: str = "temp"  # Local working directory for downloaded media
    temp_max_age_hours: float = 24.0  # Remove temp files older than this many hours at startup
    web_password: str = ""  # Optional password for the web status page
    max_concurrent_tasks: int = 1  # Maximum media groups processed at once
    min_free_disk_mb: int = 1024  # Pause downloads below this local free space

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "phone": self.phone,
            "bot_token": self.bot_token,
            "admin_ids": self.admin_ids,
            "tasks": [t.to_dict() for t in self.tasks],
            "temp_dir": self.temp_dir,
            "temp_max_age_hours": self.temp_max_age_hours,
            "web_password": self.web_password,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "min_free_disk_mb": self.min_free_disk_mb
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        tasks = [ForwardTask.from_dict(t) for t in data.get("tasks", [])]
        return cls(
            api_id=data["api_id"],
            api_hash=data["api_hash"],
            phone=data["phone"],
            bot_token=data.get("bot_token", ""),
            admin_ids=data.get("admin_ids", []),
            tasks=tasks,
            temp_dir=data.get("temp_dir", "temp"),
            temp_max_age_hours=data.get("temp_max_age_hours", 24.0),
            web_password=data.get("web_password", ""),
            max_concurrent_tasks=max(1, int(data.get("max_concurrent_tasks", 1))),
            min_free_disk_mb=max(0, int(data.get("min_free_disk_mb", 1024)))
        )


@dataclass
class TaskStatus:
    """Runtime status of a forwarding task."""
    task_id: str
    status: str  # "running", "paused", "stopped", "completed"
    progress: Optional[TaskProgress] = None
    config: Optional[ForwardTask] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress.to_dict() if self.progress else None,
            "config": self.config.to_dict() if self.config else None
        }


@dataclass
class ForwardResult:
    """Result of a message forwarding operation."""
    success: bool
    method: str  # "direct" or "download"
    error: Optional[str] = None
    forwarded_count: int = 0  # number of media messages actually forwarded

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
