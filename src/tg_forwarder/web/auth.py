"""Fixed-lifetime administrator sessions, owned by the runtime event loop."""
import hmac
import secrets
import time

from tg_forwarder.storage.passwords import verify_password
from tg_forwarder.tasks.errors import OperationError

COOKIE_NAME = "tg_forwarder_session"


class AuthSessions:
    def __init__(self, config):
        self.config = config
        self.sessions = {}
        self.failures = {}

    def _entry(self, token):
        now = time.time()
        current = self.config()
        self.sessions = {key: value for key, value in self.sessions.items()
            if value["expires_at"] > now and value["password_version"] == current.web_password}
        return self.sessions.get(token)

    def info(self, token):
        entry = self._entry(token)
        return {"auth_required": bool(self.config().web_password), "authenticated": bool(entry),
            "csrf_token": entry["csrf_token"] if entry else "",
            "expires_at": entry["expires_at"] if entry else 0}

    def login(self, password, address):
        now = time.time()
        self.failures = {key: values for key, values in self.failures.items() if values and now - values[-1] < 60}
        recent = [at for at in self.failures.get(address, []) if now - at < 60]
        if len(recent) >= 10:
            raise OperationError("login_rate_limited", "登录尝试过多，请稍后重试", 429)
        config = self.config()
        if config.web_password and not verify_password(config.web_password, password):
            self.failures[address] = recent + [now]
            raise OperationError("invalid_password", "管理密码不正确", 401)
        if not isinstance(password, str):
            raise ValueError("管理密码必须是文字")
        self.failures.pop(address, None)
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {"expires_at": now + config.web_auth_ttl_hours * 3600,
            "csrf_token": secrets.token_urlsafe(32), "password_version": config.web_password}
        return dict(self.info(token), token=token)

    def authorize(self, token, csrf=None, write=False):
        entry = self._entry(token)
        if not entry:
            raise OperationError("unauthorized", "登录已过期，请重新登录", 401)
        if write and (not csrf or not hmac.compare_digest(csrf, entry["csrf_token"])):
            raise OperationError("invalid_csrf", "会话校验失败，请刷新后重试", 403)

    def logout(self, token):
        self.sessions.pop(token, None)
        return {"success": True}
