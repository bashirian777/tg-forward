"""Video requirement qualifies a whole source group without discarding its photos."""
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import types

from tg_forwarder.bot.app import ForwarderBot
from tg_forwarder.cli import create_parser
from tg_forwarder.forwarding.engine import Forwarder
from tg_forwarder.forwarding.handler import MessageHandler
from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.storage.dedup_store import DedupTracker
from tg_forwarder.tasks.models import ForwardTask
from tests.http_support import http_client, login
from tests.support import manager, startup, video, wrapper


def photo(message_id):
    return SimpleNamespace(id=message_id, text="photo", message="photo", grouped_id=None,
        media=types.MessageMediaPhoto(photo=types.Photo(id=1000 + message_id, access_hash=1,
            file_reference=b"photo", date=None, sizes=[], dc_id=2)))


def make_handler(tmp_path, dedup=None):
    client = wrapper()
    client.get_entity = AsyncMock(return_value="target")
    client.input_media_with_cover = lambda message: message.media
    client.send_existing_media = AsyncMock(return_value=True)
    return client, MessageHandler(client, str(tmp_path), dedup_tracker=dedup, min_free_disk_mb=0)


@pytest.mark.parametrize("require_video", [False, True])
@pytest.mark.parametrize("hide_source", [False, True])
@pytest.mark.parametrize("kinds", [("photo",), ("photo", "photo"), ("video",), ("photo", "video"), ("video", "video")])
async def test_requirement_filters_photo_only_groups_and_preserves_mixed_albums(tmp_path, kinds, hide_source, require_video):
    client, handler = make_handler(tmp_path)
    messages = [(photo if kind == "photo" else video)(10 + i) for i, kind in enumerate(kinds)]
    result = await handler.forward_message_group(messages, -1001, -1002,
        hide_source=hide_source, require_video=require_video)
    assert result.success
    if require_video and "video" not in kinds:
        assert result.method == "no_video" and result.forwarded_count == 0
        client.send_existing_media.assert_not_awaited()
    else:
        assert result.forwarded_count == len(messages)
        client.send_existing_media.assert_awaited_once()
        assert client.send_existing_media.await_args.kwargs["message_ids"] == [m.id for m in messages]


async def test_single_message_entry_honors_video_requirement(tmp_path):
    client, handler = make_handler(tmp_path)
    result = await handler.forward_message(photo(10), -1001, -1002, require_video=True)
    assert result.success and result.method == "no_video"
    client.send_existing_media.assert_not_awaited()


async def test_skipped_photos_advance_checkpoint_without_counting_or_deduplicating(state, tmp_path):
    cm, tracker, original = state
    task = replace(original, require_video=True, deduplicate=True, hide_source=False)
    cm.update_task(task)
    dedup = DedupTracker(task.task_id, database=cm.db)
    client, handler = make_handler(tmp_path, dedup)
    engine = Forwarder(client, handler, tracker)
    messages = [photo(1), photo(2), photo(3), video(4), video(5)]
    groups = [messages[:1], messages[1:3], messages[3:]]
    engine._ordered_ids = [m.id for m in messages]
    for group in groups[:2]:
        assert await engine.process_message_group(group, task) == "no_video"
        assert tracker.get_task_progress(task.task_id).forwarded_count == 0
    assert tracker.get_last_message_id(task.task_id) == 3
    assert cm.db.dedup_ids(task.task_id) == set()
    assert await engine.process_message_group(groups[2], task) == "forwarded"
    assert tracker.get_last_message_id(task.task_id) == 5
    assert tracker.get_task_progress(task.task_id).forwarded_count == 2
    assert cm.db.dedup_ids(task.task_id) == {"doc_104", "doc_105"}


async def test_video_on_next_history_page_qualifies_complete_album(state, tmp_path):
    _, tracker, original = state
    task = replace(original, require_video=True, hide_source=False)
    client, handler = make_handler(tmp_path)
    messages = [photo(49), photo(50), video(51)]
    for message in messages:
        message.grouped_id = 700
    client.get_messages = AsyncMock(side_effect=[messages[:2], [messages[2], photo(52)]])
    engine = Forwarder(client, handler, tracker)
    engine._running = True
    batch = await engine._fetch_batch(task, 48)
    assert [m.id for m in batch] == [49, 50, 51]
    engine._ordered_ids = [m.id for m in batch]
    assert await engine.process_message_group(batch, task) == "forwarded"
    assert client.send_existing_media.await_args.kwargs["message_ids"] == [49, 50, 51]
    assert tracker.get_last_message_id(task.task_id) == 51
    assert tracker.get_task_progress(task.task_id).forwarded_count == 3


async def test_video_requirement_does_not_change_per_media_dedup(state, tmp_path):
    cm, _, task = state
    dedup = DedupTracker(task.task_id, database=cm.db)
    prior = video(11)
    dedup.mark_as_sent(prior)
    client, handler = make_handler(tmp_path, dedup)
    result = await handler.forward_message_group([photo(10), prior], task.source_channel,
        task.target_channel, require_video=True, deduplicate=True, hide_source=False)
    assert result.success and result.forwarded_count == 1
    assert client.send_existing_media.await_args.kwargs["message_ids"] == [10]
    assert cm.db.dedup_ids(task.task_id) == {"doc_111", "photo_1010"}


async def test_video_in_another_source_topic_does_not_qualify_photos(tmp_path):
    client, handler = make_handler(tmp_path)
    selected, other = photo(10), video(11)
    selected.reply_to = SimpleNamespace(reply_to_top_id=20)
    other.reply_to = SimpleNamespace(reply_to_top_id=30)
    result = await handler.forward_message_group([selected, other], -1001, -1002,
        source_topic_id=20, require_video=True)
    assert result.success and result.method == "no_video"
    client.send_existing_media.assert_not_awaited()


def test_old_task_without_field_defaults_to_disabled(state):
    cm, _, task = state
    old = task.to_dict()
    old.pop("require_video")
    with cm.db.connection() as db:
        db.execute("UPDATE tasks SET data=? WHERE task_id=?", (json.dumps(old), task.task_id))
    reloaded = ConfigManager(cm.db.path)
    reloaded.load_config()
    assert reloaded.get_task(task.task_id).require_video is False
    assert reloaded.get_task(task.task_id).to_dict()["require_video"] is False
    assert ForwardTask.from_dict(old).require_video is False


def test_video_switch_round_trip_and_invalid_boolean_leave_state_unchanged(state, tmp_path):
    with http_client(state, tmp_path) as (client, _):
        headers = login(client)
        task = client.get("/api/tasks/task").json
        assert task["config"]["require_video"] is False
        payload = dict(task["config"], require_video=True, revision=task["revision"])
        assert client.put("/api/tasks/task", headers=headers, json=payload).status_code == 200
        enabled = client.get("/api/tasks/task").json
        assert enabled["config"]["require_video"] is True
        invalid = dict(enabled["config"], require_video="true", revision=enabled["revision"])
        assert client.put("/api/tasks/task", headers=headers, json=invalid).status_code == 400
        assert client.get("/api/tasks/task").json == enabled
        payload = dict(enabled["config"], require_video=False, revision=enabled["revision"])
        assert client.put("/api/tasks/task", headers=headers, json=payload).status_code == 200
        assert client.get("/api/tasks/task").json["config"]["require_video"] is False


def test_cli_exposes_video_requirement():
    parser = create_parser()
    arguments = ["add", "video_task", "--source", "-1001", "--target", "-1002"]
    assert parser.parse_args(arguments).require_video is False
    assert parser.parse_args(arguments + ["--require-video"]).require_video is True


@pytest.mark.parametrize("selection,enabled", [("1", True), ("-", False)])
async def test_bot_wizard_saves_video_requirement(state, tmp_path, selection, enabled):
    cm, _, original = state
    bot = ForwarderBot(startup(tmp_path), manager(state))
    pending = {"step": "deduplicate", "task_id": "bot_video", "source": original.source_channel,
        "target": original.target_channel, "min_delay": 0, "max_delay": 0, "note": "", "prefix": ""}
    bot._pending_tasks[123] = pending
    event = SimpleNamespace(sender_id=123, text="-", respond=AsyncMock())
    await bot._handle_add_step(event)
    assert pending["step"] == "require_video"
    event.text = selection
    await bot._handle_add_step(event)
    assert pending["step"] == "include_topic_name" and pending["require_video"] is enabled
    event.text = "-"
    await bot._handle_add_step(event)
    assert pending["step"] == "start_id"
    event.text = "0"
    await bot._handle_add_step(event)
    assert cm.get_task("bot_video").require_video is enabled
    assert cm.db.get_task("bot_video")["require_video"] is enabled
