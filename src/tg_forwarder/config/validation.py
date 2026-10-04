"""Validation for the persisted runtime settings."""
import math
from .paths import PROJECT_ROOT, project_path
from tg_forwarder.tasks.validation import ValidationError

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
