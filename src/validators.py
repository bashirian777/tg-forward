"""Input validation shared by all management interfaces."""
import math
import re
from .paths import PROJECT_ROOT, project_path


class ValidationError(ValueError):
    pass


def validate_channel_id(channel_id):
    if type(channel_id) is not int or channel_id >= 0:
        return False, "Channel/group ID must be a negative integer"
    return True, None


def validate_delay_range(min_delay, max_delay):
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (min_delay, max_delay)):
        return False, "Delay must be a finite nonnegative number"
    if min_delay > max_delay:
        return False, "Minimum delay cannot exceed maximum delay"
    return True, None


def validate_task_id(task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", task_id):
        return False, "Task ID must contain 1-48 letters, digits, underscores or hyphens"
    return True, None


def validate_task(task):
    for valid, error in (validate_task_id(task.task_id), validate_channel_id(task.source_channel),
                         validate_channel_id(task.target_channel), validate_delay_range(task.min_delay, task.max_delay)):
        if not valid:
            raise ValidationError(error)
    if task.source_channel == task.target_channel:
        raise ValidationError("Source and target must differ to prevent forwarding loops")
    for name in ("enabled", "hide_source", "remove_hashtags", "send_as_channel", "deduplicate"):
        if type(getattr(task, name)) is not bool:
            raise ValidationError(f"{name} must be a boolean")
    for name in ("source_topic_id", "target_topic_id"):
        value = getattr(task, name)
        if value is not None and (type(value) is not int or value < 1):
            raise ValidationError(f"{name} must be a positive integer or null")
    for name in ("filter_keywords", "required_hashtags"):
        values = getattr(task, name)
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValidationError(f"{name} must contain nonempty strings")
    for name in ("note", "caption_prefix"):
        if not isinstance(getattr(task, name), str):
            raise ValidationError(f"{name} must be a string")
    if not task.hide_source and (task.caption_prefix or task.remove_hashtags or task.send_as_channel):
        raise ValidationError("Showing the source cannot be combined with caption edits or send-as")


def validate_runtime_config(config, project_root=PROJECT_ROOT):
    for name in ("temp_max_age_hours", "web_auth_ttl_hours"):
        value = getattr(config, name)
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValidationError(f"{name} must be a finite nonnegative number")
    if config.web_auth_ttl_hours <= 0:
        raise ValidationError("Login lifetime must be positive")
    for name, low, high in (("max_concurrent_tasks", 1, 32), ("min_free_disk_mb", 0, 10**7),
                            ("download_workers", 1, 16), ("upload_workers", 1, 16)):
        value = getattr(config, name)
        if type(value) is not int or not low <= value <= high:
            raise ValidationError(f"{name} must be an integer between {low} and {high}")
    if not isinstance(config.temp_dir, str) or not config.temp_dir.strip():
        raise ValidationError("Temporary directory cannot be empty")
    path = project_path(config.temp_dir, project_root)
    if path.exists() and not path.is_dir():
        raise ValidationError("Temporary path must be a directory")
    if path == type(path)(path.anchor):
        raise ValidationError("Filesystem root cannot be a temporary directory")
    config.temp_dir = str(path)
    if not isinstance(config.web_password, str):
        raise ValidationError("Password must be a string")
