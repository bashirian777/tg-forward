"""Topic captions use literal names between the configured prefix and source text."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import functions, types
from telethon.errors import ChatForwardsRestrictedError, FloodWaitError
from telethon.helpers import add_surrogate

from tg_forwarder.bot.app import ForwarderBot
from tg_forwarder.cli import create_parser
from tg_forwarder.forwarding.engine import Forwarder
from tg_forwarder.forwarding.handler import MessageHandler
from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.storage.dedup_store import DedupTracker
from tg_forwarder.telegram.artwork import MediaArtwork
from tg_forwarder.telegram.sender import ReliableSender
from tests.http_support import http_client, login
from tests.support import manager, startup, video, wrapper


def make_handler(tmp_path):
    client = wrapper()
    client.get_entity = AsyncMock(return_value="target")
    client.get_source_topic_name = AsyncMock(return_value="topic1")
    client.get_caption_limit = AsyncMock(return_value=1024)
    client.send_existing_media = AsyncMock(return_value=True)
    return client, MessageHandler(client, str(tmp_path), min_free_disk_mb=0)


@pytest.mark.parametrize("prefix,text,expected", [
    ("【video1】前缀", "title1", "【video1】前缀 #topic1 title1"),
    ("", "title1", "#topic1 title1"),
    ("前缀", "", "前缀 #topic1"),
    ("", "", "#topic1"),
])
@pytest.mark.parametrize("album", [False, True])
async def test_topic_name_order_without_delimiters_for_single_and_album(tmp_path, prefix, text, expected, album):
    client, handler = make_handler(tmp_path)
    messages = [video(10), video(11)] if album else [video(10)]
    for msg in messages:
        msg.text = msg.message = ""
    messages[-1].text = messages[-1].message = text
    result = await handler.forward_message_group(messages, -1001, -1002,
        caption_prefix=prefix, include_topic_name=True, target_topic_id=42)
    assert result.success and result.forwarded_count == len(messages)
    caption = client.send_existing_media.await_args.kwargs["caption"]
    assert isinstance(caption, types.TextWithEntities) and caption.text == expected
    assert "{" not in caption.text and "}" not in caption.text
    assert client.send_existing_media.await_args.kwargs["reply_to"] == 42
    client.get_source_topic_name.assert_awaited_once_with(-1001, messages[0])


async def test_literal_topic_text_preserves_prefix_and_original_formatting(tmp_path):
    client, handler = make_handler(tmp_path)
    client.get_source_topic_name.return_value = "**topic** [name](https://example.test)"
    msg = video()
    msg.text = msg.message = "**原文** #保留 #删除"
    await handler.forward_message_group([msg], -1001, -1002, caption_prefix="**前缀😀**",
        include_topic_name=True, remove_hashtags=True, required_hashtags=["删除"])
    caption = client.send_existing_media.await_args.kwargs["caption"]
    assert caption.text == "前缀😀 #**topic** [name](https://example.test) 原文 #保留"
    assert len(caption.entities) == 2
    assert all(isinstance(entity, types.MessageEntityBold) for entity in caption.entities)
    encoded = add_surrogate(caption.text)
    assert [encoded[e.offset:e.offset + e.length] for e in caption.entities] == [add_surrogate("前缀😀"), "原文"]


@pytest.mark.parametrize("options,outcome", [
    ({"filter_keywords": ["caption"]}, "filtered"),
    ({"required_hashtags": ["missing"]}, "no_hashtag"),
    ({"source_topic_id": 99}, "skip"),
])
async def test_skipped_groups_do_not_query_topic_names(tmp_path, options, outcome):
    client, handler = make_handler(tmp_path)
    result = await handler.forward_message_group([video()], -1001, -1002,
        include_topic_name=True, **options)
    assert result.success and result.method == outcome
    client.get_source_topic_name.assert_not_awaited()
    client.send_existing_media.assert_not_awaited()


@pytest.mark.parametrize("options", [{}, {"include_topic_name": False}, {"include_topic_name": True, "hide_source": False}])
async def test_disabled_or_native_forward_does_not_query_topics(tmp_path, options):
    client, handler = make_handler(tmp_path)
    result = await handler.forward_message_group([video()], -1001, -1002, **options)
    assert result.success
    client.get_source_topic_name.assert_not_awaited()


@pytest.mark.parametrize("name,limit", [(None, 1024), ("topic1", 8)])
async def test_no_topic_or_caption_overflow_keeps_existing_text(tmp_path, name, limit):
    client, handler = make_handler(tmp_path)
    client.get_source_topic_name.return_value = name
    client.get_caption_limit.return_value = limit
    await handler.forward_message_group([video()], -1001, -1002, caption_prefix="前缀", include_topic_name=True)
    assert client.send_existing_media.await_args.kwargs["caption"] == "前缀 caption"


async def test_remaining_album_media_still_get_topic_after_dedup_and_engine_passes_switch(state, tmp_path):
    cm, tracker, task = state
    task = replace(task, include_topic_name=True, deduplicate=True, caption_prefix="prefix")
    cm.update_task(task)
    client, handler = make_handler(tmp_path)
    handler.dedup_tracker = DedupTracker(task.task_id, database=cm.db)
    first, second = video(10), video(11)
    handler.dedup_tracker.mark_as_sent(first)
    engine = Forwarder(client, handler, tracker)
    engine._ordered_ids = [10, 11]
    assert await engine.process_message_group([first, second], task) == "forwarded"
    assert client.send_existing_media.await_args.kwargs["caption"].text == "prefix #topic1 caption"
    assert client.send_existing_media.await_args.kwargs["message_ids"] == [11]
    assert tracker.get_task_progress(task.task_id).forwarded_count == 1
    client.get_source_topic_name.reset_mock()
    assert await engine.process_message_group([second], task) == "duplicate"
    client.get_source_topic_name.assert_not_awaited()


@pytest.mark.parametrize("album", [False, True])
async def test_copy_and_download_fallback_use_the_same_caption(tmp_path, album):
    client, handler = make_handler(tmp_path)
    messages = [video(10), video(11)] if album else [video(10)]
    client.send_existing_media.side_effect = ChatForwardsRestrictedError(None)
    client.prepare_media_artwork = AsyncMock(side_effect=lambda message, *args: MediaArtwork(message))
    source = tmp_path / "video.mp4"
    source.write_bytes(b"media")
    client.download_media = AsyncMock(return_value=str(source))
    client.upload_media_for_album = AsyncMock(return_value=types.InputMediaPhoto(types.InputPhoto(1, 2, b"ref")))
    client.send_uploaded_album = AsyncMock(return_value=True)
    client.send_file_with_metadata = AsyncMock(return_value=True)
    result = await handler.forward_message_group(messages, -1001, -1002,
        caption_prefix="prefix", include_topic_name=True)
    assert result.success
    initial = client.send_existing_media.await_args.kwargs["caption"]
    forwarded = (client.send_uploaded_album if album else client.send_file_with_metadata).await_args.kwargs["caption"]
    assert forwarded is initial and forwarded.text == "prefix #topic1 caption"


@pytest.mark.parametrize("reply,expected", [
    (None, 1),
    (types.MessageReplyHeader(reply_to_msg_id=70), 1),  # ordinary General reply
    (types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=20), 20),
    (types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=70, reply_to_top_id=20), 20),
])
async def test_forum_lookup_distinguishes_general_replies_and_topic_roots(reply, expected):
    client = wrapper()
    entity = SimpleNamespace(forum=True)
    client.get_entity = AsyncMock(return_value=entity)
    client._client.return_value = SimpleNamespace(topics=[SimpleNamespace(id=expected, title="topic name")])
    msg = video()
    msg.reply_to = reply
    assert await client.get_source_topic_name(-1001, msg) == "topic name"
    request = client._client.await_args.args[0]
    assert isinstance(request, functions.messages.GetForumTopicsByIDRequest)
    assert request.peer is entity and request.topics == [expected]
    assert await client.get_source_topic_name(-1001, msg) == "topic name"
    client.get_entity.assert_awaited_once()
    client._client.assert_awaited_once()


async def test_non_forum_replies_never_query_topic_api():
    client = wrapper()
    client.get_entity = AsyncMock(return_value=SimpleNamespace(forum=False))
    msg = video()
    msg.reply_to = types.MessageReplyHeader(reply_to_top_id=20, reply_to_msg_id=21)
    assert await client.get_source_topic_name(-1001, msg) is None
    client._client.assert_not_awaited()


async def test_topic_cache_refreshes_names_scopes_sources_and_retries_missing_names(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("tg_forwarder.telegram.client.time.monotonic", lambda: clock[0])
    client = wrapper()
    client.get_entity = AsyncMock(return_value=SimpleNamespace(forum=True))
    client._client.side_effect = [SimpleNamespace(topics=[SimpleNamespace(id=20, title="old")]),
        SimpleNamespace(topics=[SimpleNamespace(id=20, title="other group")]),
        SimpleNamespace(topics=[types.ForumTopicDeleted(20)]),
        SimpleNamespace(topics=[SimpleNamespace(id=20, title="renamed")])]
    msg = video()
    msg.reply_to = types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=20)
    assert await client.get_source_topic_name(-1001, msg) == "old"
    assert await client.get_source_topic_name(-1002, msg) == "other group"
    assert await client.get_source_topic_name(-1001, msg) == "old"
    clock[0] += 301
    assert await client.get_source_topic_name(-1001, msg) is None
    clock[0] += 30
    assert await client.get_source_topic_name(-1001, msg) is None
    clock[0] += 31
    assert await client.get_source_topic_name(-1001, msg) == "renamed"
    assert client._client.await_count == 4


@pytest.mark.parametrize("stage", ["source", "topic"])
async def test_lookup_failures_fall_back_but_flood_wait_and_cancellation_propagate(stage):
    client = wrapper()
    client.get_entity = AsyncMock(return_value=SimpleNamespace(forum=True))
    failure = client.get_entity if stage == "source" else client._client
    failure.side_effect = RuntimeError("unavailable")
    assert await client.get_source_topic_name(-1001, video()) is None
    assert await client.get_source_topic_name(-1001, video()) is None
    assert failure.await_count == 1
    for error in (FloodWaitError(None, capture=12), asyncio.CancelledError()):
        client._topic_sources.clear()
        client._topic_names.clear()
        failure.side_effect = error
        with pytest.raises(type(error)):
            await client.get_source_topic_name(-1001, video())


async def test_caption_limit_uses_server_value_and_caches_it():
    client = wrapper()
    client._client.return_value = SimpleNamespace(caption_length_max=2048)
    assert await client.get_caption_limit() == 2048
    assert await client.get_caption_limit() == 2048
    assert isinstance(client._client.await_args.args[0], functions.help.GetConfigRequest)
    client._client.assert_awaited_once()
    other = wrapper()
    other._client.side_effect = RuntimeError("unavailable")
    assert await other.get_caption_limit() == 1024


async def test_reliable_retry_retains_literal_caption_after_topic_rename(state):
    cm, _, _ = state
    client = AsyncMock(side_effect=[TimeoutError("lost response"), None])
    client.get_input_entity.return_value = types.InputPeerChannel(1, 2)
    sender = ReliableSender(client, cm.db)
    media = types.InputMediaPhoto(types.InputPhoto(1, 2, b"ref"))
    original = types.TextWithEntities("prefix **topic** title", [types.MessageEntityBold(0, 6)])
    with pytest.raises(TimeoutError):
        await sender.send(1, media, task_id="task", message_ids=[10], caption=original)
    await sender.send(1, media, task_id="task", message_ids=[10], caption=types.TextWithEntities("renamed", []))
    first, second = [call.args[0] for call in client.await_args_list]
    assert first.message == second.message == original.text
    assert first.random_id == second.random_id
    assert [e.to_dict() for e in second.entities] == [e.to_dict() for e in original.entities]
    await sender.send(1, media, task_id="task", message_ids=[10], caption=original)
    assert client.await_count == 2


async def test_reliable_album_places_literal_topic_caption_only_on_first_item(state):
    cm, _, _ = state
    client = AsyncMock()
    client.get_input_entity.return_value = types.InputPeerChannel(1, 2)
    sender = ReliableSender(client, cm.db)
    media = [types.InputMediaPhoto(types.InputPhoto(i, 2, b"ref")) for i in (1, 2)]
    caption = types.TextWithEntities("prefix [topic](url) title", [])
    await sender.send(1, media, task_id="task", message_ids=[10, 11], caption=caption, reply_to=42)
    request = client.await_args.args[0]
    assert isinstance(request, functions.messages.SendMultiMediaRequest)
    assert [item.message for item in request.multi_media] == [caption.text, ""]
    assert all(item.entities == [] for item in request.multi_media)
    assert request.reply_to.reply_to_msg_id == 42


async def test_unmanaged_album_keeps_name_literal_and_only_uses_one_caption():
    client = wrapper()
    caption = types.TextWithEntities("prefix **topic** title", [])
    media = [types.InputMediaPhoto(types.InputPhoto(i, 2, b"ref")) for i in (1, 2)]
    await client.send_existing_media(1, media, caption=caption)
    kwargs = client._client.send_file.await_args.kwargs
    assert kwargs["caption"] == caption.text and kwargs["parse_mode"] is None
    assert kwargs["formatting_entities"] == []


def test_old_configs_default_off_and_http_validates_boolean_and_source_mode(state, tmp_path):
    cm, _, task = state
    old = task.to_dict()
    old.pop("include_topic_name")
    with cm.db.connection() as db:
        db.execute("UPDATE tasks SET data=? WHERE task_id=?", (json.dumps(old), task.task_id))
    cm.reload()
    assert cm.get_task(task.task_id).include_topic_name is False
    with http_client(state, tmp_path) as (client, _):
        headers = login(client)
        snapshot = client.get("/api/tasks/task").json
        payload = dict(snapshot["config"], include_topic_name=True, revision=snapshot["revision"])
        assert client.put("/api/tasks/task", headers=headers, json=payload).status_code == 200
        enabled = client.get("/api/tasks/task").json
        assert enabled["config"]["include_topic_name"] is True
        for value in ("true", 1, None):
            invalid = dict(enabled["config"], include_topic_name=value, revision=enabled["revision"])
            assert client.put("/api/tasks/task", headers=headers, json=invalid).status_code == 400
            assert client.get("/api/tasks/task").json == enabled
        invalid = dict(enabled["config"], hide_source=False, revision=enabled["revision"])
        assert client.put("/api/tasks/task", headers=headers, json=invalid).status_code == 400
        assert client.get("/api/tasks/task").json == enabled
        disabled = dict(enabled["config"], include_topic_name=False, hide_source=False, revision=enabled["revision"])
        assert client.put("/api/tasks/task", headers=headers, json=disabled).status_code == 200


def test_cli_exposes_topic_name_option():
    arguments = ["add", "named", "--source", "-1001", "--target", "-1002"]
    parser = create_parser()
    assert parser.parse_args(arguments).include_topic_name is False
    assert parser.parse_args(arguments + ["--include-topic-name"]).include_topic_name is True


@pytest.mark.parametrize("selection,enabled", [("1", True), ("-", False)])
async def test_bot_wizard_persists_topic_name_option(state, tmp_path, selection, enabled):
    cm, _, task = state
    bot = ForwarderBot(startup(tmp_path), manager(state))
    pending = {"step": "require_video", "task_id": "bot_topic", "source": task.source_channel,
        "target": task.target_channel, "min_delay": 0, "max_delay": 0, "note": "", "prefix": ""}
    bot._pending_tasks[123] = pending
    event = SimpleNamespace(sender_id=123, text="-", respond=AsyncMock())
    await bot._handle_add_step(event)
    assert pending["step"] == "include_topic_name"
    event.text = selection
    await bot._handle_add_step(event)
    assert pending["step"] == "start_id"
    event.text = "0"
    await bot._handle_add_step(event)
    assert cm.get_task("bot_topic").include_topic_name is enabled
    assert cm.db.get_task("bot_topic")["include_topic_name"] is enabled
