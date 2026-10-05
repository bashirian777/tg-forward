"""Offline Flask test runtime; Telegram connection workers never start."""
from dataclasses import replace
from contextlib import contextmanager
from unittest.mock import AsyncMock

from tg_forwarder.runtime.bridge import RuntimeBridge
from tg_forwarder.runtime.service import ForwarderService
from tg_forwarder.web.app import create_app
from tests.support import startup


@contextmanager
def http_client(state, tmp_path, password=None, dist_dir=None):
    cm, tracker, _ = state
    if password is not None:
        cm.save_app_config(replace(cm.get_config(), web_password=password))
    def factory():
        service = ForwarderService(startup(tmp_path), cm, tracker)
        service.start_background = AsyncMock()
        return service
    runtime = RuntimeBridge(factory).start()
    try:
        yield create_app(runtime, dist_dir).test_client(), runtime
    finally:
        runtime.stop()


def login(client, password=""):
    response = client.post("/api/auth", json={"password": password})
    assert response.status_code == 200, response.json
    return {"X-CSRF-Token": response.json["csrf_token"]}
