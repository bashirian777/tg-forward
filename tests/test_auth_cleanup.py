"""Authentication lifetime and owned file cleanup checks."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.web_server import WebServer
from src.workspace import WorkspaceStore
from tests.test_controls import manager
from tests.test_integrity import state


@pytest.mark.asyncio
async def test_unicode_password_and_fixed_expiry(state, monkeypatch):
    mgr = manager(state)
    server = WebServer(mgr.progress_tracker, mgr, web_password="管理密码")
    clock = [1000.0]
    monkeypatch.setattr("src.web_server.time.time", lambda: clock[0])
    server._auth_token_ttl = 30
    response = await server.handle_api_auth(SimpleNamespace(json=AsyncMock(return_value={"password": "管理密码"})))
    data = json.loads(response.body)
    assert data["expires_at"] == 1030
    request = SimpleNamespace(headers={"Authorization": "Bearer " + data["token"]})
    clock[0] = 1029
    assert server._is_authorized(request)
    assert server._auth_tokens[data["token"]] == 1030
    clock[0] = 1030
    assert not server._is_authorized(request)


@pytest.mark.asyncio
async def test_auth_lifetime_hot_update_persists_and_preserves_existing_token(state):
    mgr = manager(state)
    mgr.has_running_tasks = lambda: True
    server = WebServer(mgr.progress_tracker, mgr)
    server._auth_tokens["old"] = 9999999999
    response = await server.handle_api_update_config(SimpleNamespace(json=AsyncMock(return_value={"web_auth_ttl_hours": 0.5})))
    assert response.status == 200
    assert server._auth_token_ttl == 1800
    assert server._auth_tokens["old"] == 9999999999
    mgr.config_manager.load_config()
    assert mgr.config_manager.get_config().web_auth_ttl_hours == 0.5


def test_cleanup_excludes_active_and_unowned_files(tmp_path):
    store = WorkspaceStore(tmp_path)
    inactive = store.open("a", -100123, [1])
    for name in ("video.part", "cover_a.jpg", "thumb_a.jpg"):
        (inactive / name).write_bytes(b"123")
    store.release(inactive)
    active = store.open("b", -100123, [2])
    (active / "cover_b.jpg").write_bytes(b"active")
    unrelated = tmp_path / "keep.jpg"
    unrelated.write_bytes(b"unowned")
    result = store.cleanup()
    assert result["removed"] == 3 and result["freed_bytes"] == 9
    assert result["skipped_active"] == 1
    assert unrelated.exists() and (active / "cover_b.jpg").exists()
    store.release(active)


@pytest.mark.asyncio
async def test_task_cleanup_includes_covers_and_does_not_touch_other_tasks(state):
    mgr = manager(state)
    store = WorkspaceStore(mgr.temp_dir)
    own = store.open("task", -100123, [1])
    (own / "cover.jpg").write_bytes(b"cover")
    (own / "thumb.jpg").write_bytes(b"thumb")
    store.release(own)
    other = store.open("other", -100123, [2])
    (other / "cover.jpg").write_bytes(b"other")
    store.release(other)
    result = await mgr.cleanup_task_files("task")
    assert result["removed"] == 2
    assert not own.exists() and other.exists()
