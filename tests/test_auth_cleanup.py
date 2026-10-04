"""Authentication lifetime and owned file cleanup checks."""
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from tg_forwarder.web.auth import AuthSessions
from tg_forwarder.storage.workspace import WorkspaceStore
from tests.test_controls import manager
from tests.test_media_artwork import video, wrapper
from telethon import types
from telethon.errors import ChatForwardsRestrictedError
from tg_forwarder.telegram.artwork import MediaArtwork
from tg_forwarder.forwarding.handler import MessageHandler
from tests.test_integrity import state


@pytest.mark.asyncio
async def test_managed_send_failure_reuses_upload_and_success_cleans_covers(state, tmp_path):
    cm, tracker, task = state
    client = wrapper()
    client.set_progress_tracker(tracker)
    client.get_entity = AsyncMock(return_value="target")
    client.send_existing_media = AsyncMock(side_effect=[ChatForwardsRestrictedError(None), TimeoutError("lost response"), ChatForwardsRestrictedError(None), True])
    async def artwork(message, path, task_id):
        thumb, cover = Path(path) / "thumb.jpg", Path(path) / "cover.jpg"
        thumb.write_bytes(b"thumb")
        cover.write_bytes(b"cover")
        return MediaArtwork(message, str(thumb), str(cover))
    async def download(message, path, **kwargs):
        source = Path(path) / "video.mp4"
        source.write_bytes(b"video")
        return str(source)
    client.prepare_media_artwork = artwork
    client.download_media = AsyncMock(side_effect=download)
    uploaded = types.InputMediaDocument(types.InputDocument(1, 2, b"ref"))
    client.upload_media_for_album = AsyncMock(return_value=uploaded)
    handler = MessageHandler(client, cm.get_config().temp_dir, min_free_disk_mb=0)
    source = video()
    assert not (await handler.forward_message_group([source], task.source_channel, task.target_channel, task_id=task.task_id)).success
    assert handler.workspaces.stats()["files"] >= 3  # cover, thumb and saved media reference
    assert (await handler.forward_message_group([source], task.source_channel, task.target_channel, task_id=task.task_id)).success
    client.download_media.assert_awaited_once()
    client.upload_media_for_album.assert_awaited_once()
    assert handler.workspaces.stats()["files"] == 0


@pytest.mark.parametrize("stage", ["download", "upload", "send", "cancel"])
@pytest.mark.asyncio
async def test_owned_failure_and_cancel_keep_files_until_explicit_cleanup(state, tmp_path, stage):
    import asyncio
    cm, tracker, task = state
    client = wrapper()
    client.set_progress_tracker(tracker)
    client.get_entity = AsyncMock(return_value="target")
    async def send_existing(*args, **kwargs):
        if stage == "send" and getattr(send_existing, "tried", False):
            raise TimeoutError("send interrupted")
        send_existing.tried = True
        raise ChatForwardsRestrictedError(None)
    client.send_existing_media = send_existing
    async def prepare(message, path, task_id):
        cover = Path(path) / "cover.jpg"
        cover.write_bytes(b"cover")
        return MediaArtwork(message, cover=str(cover))
    async def download(message, path, **kwargs):
        (Path(path) / "video.part").write_bytes(b"partial")
        if stage == "cancel":
            raise asyncio.CancelledError()
        if stage == "download":
            raise RuntimeError("download interrupted")
        return str(Path(path) / "video.part")
    client.prepare_media_artwork = prepare
    client.download_media = download
    client.upload_media_for_album = AsyncMock(side_effect=RuntimeError("upload interrupted") if stage == "upload" else None,
        return_value=types.InputMediaDocument(types.InputDocument(1, 2, b"ref")))
    handler = MessageHandler(client, cm.get_config().temp_dir, min_free_disk_mb=0)
    call = handler.forward_message_group([video()], task.source_channel, task.target_channel, task_id=task.task_id)
    if stage == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await call
    else:
        assert not (await call).success
    assert handler.workspaces.stats()["active"] == 0
    assert handler.workspaces.stats()["files"] > 0
    result = handler.workspaces.cleanup(task_id=task.task_id)
    assert result["removed"] > 0
    assert handler.workspaces.stats()["files"] == 0


@pytest.mark.asyncio
async def test_unicode_password_and_fixed_expiry(state, monkeypatch):
    from dataclasses import replace
    mgr = manager(state)
    mgr.config_manager.save_app_config(replace(mgr.config_manager.get_config(), web_password="管理密码", web_auth_ttl_hours=30 / 3600))
    auth = AuthSessions(mgr.config_manager.get_config)
    clock = [1000.0]
    monkeypatch.setattr("tg_forwarder.web.auth.time.time", lambda: clock[0])
    data = auth.login("管理密码", "local")
    assert data["expires_at"] == 1030
    clock[0] = 1029
    auth.authorize(data["token"])
    assert auth.info(data["token"])["expires_at"] == 1030
    clock[0] = 1030
    with pytest.raises(ValueError):
        auth.authorize(data["token"])


@pytest.mark.asyncio
async def test_auth_lifetime_hot_update_persists_and_preserves_existing_token(state):
    mgr = manager(state)
    mgr.has_running_tasks = lambda: True
    auth = AuthSessions(mgr.config_manager.get_config)
    old = auth.login("", "local")
    await mgr.update_settings({"web_auth_ttl_hours": 0.5})
    assert auth.info(old["token"])["expires_at"] == old["expires_at"]
    new = auth.login("", "local")
    assert new["expires_at"] - __import__("time").time() <= 1800
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


def test_cookie_csrf_password_rotation_and_logout(state, tmp_path):
    from tests.http_support import http_client, login
    with http_client(state, tmp_path, password="旧密码") as (client, runtime):
        assert client.get("/api/tasks").status_code == 401
        response = client.post("/api/auth", json={"password": "旧密码"})
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["Set-Cookie"]
        assert "SameSite=Strict" in response.headers["Set-Cookie"]
        headers = {"X-CSRF-Token": response.json["csrf_token"]}
        public = client.get("/api/config")
        assert "web_password" not in public.json
        assert client.put("/api/config", json={"web_auth_ttl_hours": 1}).status_code == 403
        assert client.put("/api/config", headers=headers, json={"web_password": None}).status_code == 400
        assert client.put("/api/config", headers=headers, json={"web_password": "新密码"}).status_code == 200
        assert client.get("/api/tasks").status_code == 401
        assert client.post("/api/auth", json={"password": "旧密码"}).status_code == 401
        headers = login(client, "新密码")
        assert client.delete("/api/auth", headers=headers).status_code == 200
        assert client.get("/api/tasks").status_code == 401


def test_login_rate_limit_blocks_repeated_wrong_passwords(state, tmp_path):
    from tests.http_support import http_client
    with http_client(state, tmp_path, password="管理密码") as (client, runtime):
        for _ in range(10):
            assert client.post("/api/auth", json={"password": "错误"}).status_code == 401
        assert client.post("/api/auth", json={"password": "错误"}).status_code == 429
