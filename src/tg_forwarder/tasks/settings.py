"""Validation and persistence of runtime settings, without runtime locks."""
from copy import deepcopy

from tg_forwarder.config.validation import validate_runtime_config


class RuntimeSettings:
    def __init__(self, config_manager):
        self.config_manager = config_manager

    def snapshot(self):
        config = self.config_manager.get_config()
        values = deepcopy(config.settings_dict())
        values.pop("web_password", None)
        return dict(values, revision=self.config_manager.revision,
            web_password_configured=bool(config.web_password), storage_source="SQLite")

    def prepare_update(self, data):
        current = self.config_manager.get_config()
        candidate = deepcopy(current)
        allowed = candidate.setting_names()
        if set(data) - allowed - {"revision"}:
            raise ValueError("包含不支持的运行设置")
        for name in allowed & data.keys():
            if name == "web_password":
                if not isinstance(data[name], str):
                    raise ValueError("管理密码必须是文字")
                if not data[name]:
                    continue
            setattr(candidate, name, data[name])
        validate_runtime_config(candidate, self.config_manager.project_root)
        runtime_keys = allowed - {"web_password", "web_auth_ttl_hours"}
        changed = any(getattr(candidate, key) != getattr(current, key) for key in runtime_keys)
        return candidate, changed

    def persist(self, candidate, expected_revision=None):
        self.config_manager.save_app_config(candidate, expected_revision)

    def log_update(self, candidate):
        keys = candidate.setting_names() - {"web_password"}
        self.config_manager.db.log_operation("update_app_config", after_data={
            key: getattr(candidate, key) for key in keys})
