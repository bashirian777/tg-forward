"""Local HTTP integration and legacy SQLite compatibility."""
import json
import sqlite3
from unittest.mock import AsyncMock
from dataclasses import replace
import pytest
from tg_forwarder.storage.database import Database
from tests.http_support import http_client, login
from tg_forwarder.forwarding.handler import MessageHandler
from tg_forwarder.tasks.validation import validate_task
from tests.test_integrity import state
from tests.test_media_artwork import wrapper


def test_old_sqlite_schema_migrates_and_preserves_checkpoint(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE app_settings(id INTEGER PRIMARY KEY,data TEXT,updated_at TEXT); CREATE TABLE tasks(task_id TEXT PRIMARY KEY,data TEXT,updated_at TEXT);")
        conn.execute("INSERT INTO tasks VALUES(?,?,?)", ("old", json.dumps({"task_id": "old"}), "before"))
    db = Database(str(path))
    db.save_progress({"task_id": "old", "last_message_id": 123, "forwarded_count": 10})
    db.save_task({"task_id": "old", "note": "updated"}, expected_revision=1)
    assert db.revision("old") == 2
    assert db.get_progress("old")["last_message_id"] == 123


def test_http_auth_config_and_conflict(state, tmp_path):
    with http_client(state, tmp_path, password="密码") as (client, runtime):
        assert client.get("/api/config").status_code == 401
        headers = login(client, "密码")
        config = client.get("/api/config").json
        assert config["web_auth_ttl_hours"] == 24
        assert client.put("/api/config", headers=headers, json={"revision": config["revision"], "web_auth_ttl_hours": 2}).status_code == 200
        assert client.put("/api/config", headers=headers, json={"revision": config["revision"], "web_auth_ttl_hours": 1}).status_code == 409
        assert client.put("/api/config", json={"web_auth_ttl_hours": 1}).status_code == 403
        assert client.put("/api/config", headers=headers, json={"web_password": "新密码"}).status_code == 200
        assert client.get("/api/config").status_code == 401
        login(client, "新密码")
        assert client.get("/api/config").status_code == 200



def test_complete_hashtag_matching_preserves_larger_tags(tmp_path):
    handler = MessageHandler(wrapper(), str(tmp_path), min_free_disk_mb=0)
    message = type("Message", (), {"text": "#original_work"})()
    assert not handler._contains_required_hashtags([message], ["original"])
    assert handler._remove_hashtags_from_text("#original_work #original\nhello", ["original"]) == "#original_work \nhello"


def test_show_source_conflicts_are_rejected(state):
    task = state[2]
    with pytest.raises(ValueError):
        validate_task(replace(task, hide_source=False, caption_prefix="edit"))


@pytest.mark.asyncio
async def test_show_source_uses_native_forward(state, tmp_path):
    from tests.test_media_artwork import video
    client = wrapper()
    client.send_existing_media = AsyncMock(return_value=True)
    handler = MessageHandler(client, str(tmp_path), min_free_disk_mb=0)
    result = await handler.forward_message_group([video()], -100111, -100222, hide_source=False)
    assert result.success and result.method == "forward"
    assert client.send_existing_media.call_args.kwargs["source"] == -100111


@pytest.mark.asyncio
async def test_expired_document_refreshes_same_media(state, tmp_path, monkeypatch):
    from telethon.errors import FileReferenceExpiredError
    from tests.test_media_artwork import video
    from tg_forwarder.telegram.transfer import ParallelTransfer
    client = wrapper()
    client.set_progress_tracker(state[1])
    original, fresh = video(), video(reference=b"fresh")
    client._client.get_messages.return_value = fresh
    download = AsyncMock(side_effect=[FileReferenceExpiredError(None), str(tmp_path / "video.mp4")])
    monkeypatch.setattr(ParallelTransfer, "download", download)
    assert await client.download_media(original, str(tmp_path), task_id="task")
    assert download.await_args_list[1].args[0] is fresh


@pytest.mark.asyncio
async def test_deleted_document_during_reference_refresh_requires_operator(state, tmp_path, monkeypatch):
    from telethon.errors import FileReferenceExpiredError
    from tests.test_media_artwork import video
    from tg_forwarder.forwarding.errors import PermanentTransferError
    from tg_forwarder.telegram.transfer import ParallelTransfer
    client = wrapper()
    client.set_progress_tracker(state[1])
    client._client.get_messages.return_value = None
    download = AsyncMock(side_effect=FileReferenceExpiredError(None))
    monkeypatch.setattr(ParallelTransfer, "download", download)
    with pytest.raises(PermanentTransferError, match="deleted or replaced"):
        await client.download_media(video(), str(tmp_path), task_id="task")
    assert download.await_count == 1


def test_static_spa_and_api_paths_are_distinct(state, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script type="module" src="/assets/app-hash.js"></script>')
    (dist / "assets/app-hash.js").write_text("console.log('built')")
    with http_client(state, tmp_path, dist_dir=dist) as (client, runtime):
        for route in ("/", "/tasks", "/settings", "/resources", "/activity"):
            response = client.get(route)
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
        asset = client.get("/assets/app-hash.js")
        assert "immutable" in asset.headers["Cache-Control"]
        for route in ("/api/missing", "/assets/missing.js", "/.env", "/assets/../../.env"):
            assert client.get(route).status_code == 404
