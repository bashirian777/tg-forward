"""Mutable runtime configuration stored in SQLite."""
from dataclasses import dataclass, field, asdict, fields
from typing import List
from tg_forwarder.tasks.models import ForwardTask


@dataclass
class RuntimeConfig:
    tasks: List[ForwardTask] = field(default_factory=list)
    temp_dir: str = "temp"
    temp_max_age_hours: float = 24.0
    web_password: str = ""
    web_auth_ttl_hours: float = 24.0
    max_concurrent_tasks: int = 1
    min_free_disk_mb: int = 1024
    download_workers: int = 4
    upload_workers: int = 4

    def to_dict(self):
        return asdict(self)

    def settings_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "tasks"}

    @classmethod
    def setting_names(cls):
        return {f.name for f in fields(cls) if f.name != "tasks"}

    @classmethod
    def from_dict(cls, data):
        values = {f.name: data[f.name] for f in fields(cls) if f.name in data and f.name != "tasks"}
        values["tasks"] = [ForwardTask.from_dict(t) for t in data.get("tasks", [])]
        return cls(**values)
