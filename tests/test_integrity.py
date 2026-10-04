"""Regression tests for data preservation and safe checkpoints."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from src.config_manager import ConfigManager
from src.database import ConfigurationConflict
from src.forwarder import Forwarder
from src.models import RuntimeConfig, ForwardTask, ForwardResult
from src.progress_tracker import ProgressTracker
from src.message_handler import MessageHandler
from src.media_artwork import MediaArtwork
from tests.test_media_artwork import video, wrapper
from telethon.errors import ChatForwardsRestrictedError


@pytest.fixture
def state(tmp_path):
    cm = ConfigManager(str(tmp_path / "forwarder.db"), project_root=tmp_path)
    task = ForwardTask("task", -1001111111111, -1002222222222, 0, 0)
    cm.save_config(RuntimeConfig(tasks=[task], temp_dir=str(tmp_path / "temp")))
    return cm, ProgressTracker(database=cm.db), task


def test_config_operations_preserve_all_related_state(state):
    cm, tracker, task = state
    tracker.record_forwarded("task", 100, 10)
    tracker.begin_transfer("task", [101], 1)
    cm.db.add_dedup_ids("task", ["file"])
    cm.db.add_task_error("task", "test", "error")
    cm.save_config(cm.get_config())
    cm.update_task(replace(task, note="changed"))
    cm.add_task(replace(task, task_id="second"))
    cm.remove_task("second")
    assert cm.db.get_progress("task")["last_message_id"] == 100
    assert cm.db.get_transfer("task")["message_ids"] == [101]
    assert cm.db.dedup_ids("task") == {"file"}
    assert cm.db.task_error_summary("task")["count"] == 1


def test_stale_manager_cannot_delete_new_task_or_overwrite_edit(state):
    cm, _, task = state
    other = ConfigManager(cm.db.path)
    other.load_config()
    cm.add_task(replace(task, task_id="new"))
    other.update_task(replace(task, note="other"))
    assert cm.db.get_task("new")
    with pytest.raises(ConfigurationConflict):
        cm.update_task(replace(task, note="stale"))


@pytest.mark.asyncio
async def test_interleaved_album_receipt_survives_restart(state):
    cm, tracker, task = state
    handler = SimpleNamespace(forward_message_group=AsyncMock(side_effect=[ForwardResult(True, "copy", forwarded_count=2), ForwardResult(False, "copy")]))
    engine = Forwarder(None, handler, tracker)
    messages = [SimpleNamespace(id=i, grouped_id=99 if i != 2 else None) for i in (1, 2, 3)]
    engine._ordered_ids = [1, 2, 3]
    groups = engine._group_messages(messages)
    assert await engine.process_message_group(groups[0], task) == "forwarded"
    assert tracker.get_last_message_id("task") == 1
    assert await engine.process_message_group(groups[1], task) == "failed"
    restarted = ProgressTracker(database=cm.db)
    assert restarted.completed_ids("task") == {3}
    restarted.complete_group("task", [2], "forwarded", 1, [2, 3])
    assert restarted.get_last_message_id("task") == 3
    assert restarted.get_task_progress("task").forwarded_count == 3


@pytest.mark.asyncio
async def test_fetch_completes_boundary_album(state):
    _, tracker, task = state
    msg = lambda i, g: SimpleNamespace(id=i, grouped_id=g)
    client = SimpleNamespace(get_messages=AsyncMock(side_effect=[[msg(49, 10), msg(50, 10)], [msg(51, 10), msg(52, None)]]))
    engine = Forwarder(client, None, tracker)
    engine._running = True
    result = await engine._fetch_batch(task, 0)
    assert [m.id for m in result] == [49, 50, 51]


@pytest.mark.asyncio
async def test_live_album_settles_after_later_part_arrives(state):
    _, tracker, task = state
    msg = lambda i: SimpleNamespace(id=i, grouped_id=10)
    client = SimpleNamespace(get_messages=AsyncMock(side_effect=[[msg(1)], [], [msg(2)], [], []]))
    engine = Forwarder(client, None, tracker)
    engine._running = True
    engine.album_settle_seconds = 0
    assert [m.id for m in await engine._fetch_batch(task, 0)] == [1, 2]


@pytest.mark.asyncio
async def test_missing_album_item_does_not_advance_or_deduplicate(state, tmp_path):
    cm, tracker, task = state
    client = wrapper()
    client.set_progress_tracker(tracker)
    client.get_entity = AsyncMock(return_value="target")
    client.send_existing_media = AsyncMock(side_effect=ChatForwardsRestrictedError(None))
    client.prepare_media_artwork = AsyncMock(side_effect=lambda message, *args: MediaArtwork(message))
    source = tmp_path / "video.mp4"
    source.write_bytes(b"media")
    client.download_media = AsyncMock(side_effect=[str(source), None])
    client.upload_media_for_album = AsyncMock(return_value="handle")
    client.send_uploaded_album = AsyncMock(return_value=True)
    handler = MessageHandler(client, str(tmp_path), min_free_disk_mb=0)
    engine = Forwarder(client, handler, tracker)
    assert await engine.process_message_group([video(10), video(11)], task) == "failed"
    assert tracker.get_last_message_id(task.task_id) == 0
    assert tracker.get_task_progress(task.task_id).forwarded_count == 0
    client.send_uploaded_album.assert_not_awaited()
    assert not cm.db.dedup_ids(task.task_id)
