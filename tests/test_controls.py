"""Task controls, validation, and transport retry regression checks."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from telethon import types
from tg_forwarder.bot.app import ForwarderBot
from tg_forwarder.forwarding.engine import Forwarder
from tg_forwarder.telegram.sender import ReliableSender
from tg_forwarder.tasks.models import ForwardResult
from tg_forwarder.tasks.validation import validate_task
from tests.http_support import http_client, login
from tests.support import manager, startup


@pytest.mark.asyncio
async def test_fallback_chain_limit_follows_media_group_setting(state):
    mgr = manager(state)
    limit = mgr.config_manager.get_config().max_concurrent_tasks
    assert mgr.client.disk_semaphore._value == limit
    await mgr.update_settings({"max_concurrent_tasks": limit + 1})
    assert mgr.client.disk_semaphore._value == limit + 1


@pytest.mark.parametrize("action", ["pause", "resume"])
def test_removed_controls_rejected_without_state_changes(state, tmp_path, action):
    cm, tracker, task = state
    tracker.record_forwarded(task.task_id, 10, 1)
    with http_client(state, tmp_path) as (client, _):
        headers = login(client)
        before = client.get(f"/api/tasks/{task.task_id}").json
        response = client.post(f"/api/tasks/{task.task_id}/action", headers=headers,
            json={"action": action})
        assert response.status_code == 400
        assert response.json["error"] == "invalid_input"
        assert client.get(f"/api/tasks/{task.task_id}").json == before
    assert not any(entry["action"] == action + "_task" for entry in cm.db.list_logs())


@pytest.mark.parametrize("action", ["pause", "resume"])
@pytest.mark.asyncio
async def test_old_bot_control_buttons_are_expired(state, tmp_path, action):
    mgr = manager(state)
    bot = ForwarderBot(startup(tmp_path), mgr)
    event = SimpleNamespace(data=f"{action}_task".encode(), answer=AsyncMock())
    before = mgr.task_snapshot("task")
    logs = mgr.get_logs()
    await bot._handle_callback(event)
    event.answer.assert_awaited_once_with("操作已失效，请重新打开任务列表", alert=True)
    assert mgr.task_snapshot("task") == before
    assert mgr.get_logs() == logs


@pytest.mark.asyncio
async def test_stopped_queued_task_does_not_send(state):
    cm, tracker, task = state
    semaphore = asyncio.Semaphore(0)
    handler = SimpleNamespace(is_media_message=lambda m: True, forward_message_group=AsyncMock())
    client = SimpleNamespace(get_messages=AsyncMock(return_value=[SimpleNamespace(id=1, grouped_id=None)]))
    engine = Forwarder(client, handler, tracker, semaphore)
    runner = asyncio.create_task(engine.run_task(task))
    try:
        for _ in range(20):
            if semaphore._waiters:
                break
            await asyncio.sleep(0)
        assert semaphore._waiters
        engine.stop()
        semaphore.release()
        await asyncio.wait_for(runner, timeout=1)
        handler.forward_message_group.assert_not_awaited()
        assert tracker.get_last_message_id(task.task_id) == 0
        assert tracker.get_transfer(task.task_id) is None
    finally:
        engine.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
async def test_stop_and_start_preserve_checkpoint_and_retry_only_unfinished_group(state, monkeypatch):
    _, tracker, task = state
    mgr = manager(state)
    messages = [SimpleNamespace(id=i, grouped_id=None) for i in (10, 11)]
    mgr.client.get_messages = AsyncMock(side_effect=lambda channel, min_id, limit:
        [message for message in messages if message.id > min_id])
    entered, cancelled, fetched_after_restart = asyncio.Event(), asyncio.Event(), asyncio.Event()
    attempts = []
    interrupted = True

    class Handler:
        def __init__(self, *args, **kwargs):
            pass

        def is_media_message(self, message):
            return True

        async def forward_message_group(self, group, *args, **kwargs):
            nonlocal interrupted
            ids = [message.id for message in group]
            attempts.append(ids)
            if ids == [11] and interrupted:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    interrupted = False
                    cancelled.set()
            return ForwardResult(True, "copy", forwarded_count=len(group))

    monkeypatch.setattr("tg_forwarder.tasks.manager.MessageHandler", Handler)
    try:
        await mgr.start_task(task.task_id)
        first_runner = mgr._tasks[task.task_id]
        await asyncio.wait_for(entered.wait(), timeout=1)
        await mgr.stop_task(task.task_id)
        assert first_runner.done() and cancelled.is_set()
        assert mgr.get_task_status(task.task_id).status == "stopped"
        assert tracker.get_last_message_id(task.task_id) == 10
        assert tracker.get_task_progress(task.task_id).forwarded_count == 1
        assert tracker.get_transfer(task.task_id)["state"] == "interrupted"
        assert tracker.get_transfer(task.task_id)["message_ids"] == [11]

        async def fetch_after_restart(channel, min_id, limit):
            if min_id == 11:
                fetched_after_restart.set()
            return [message for message in messages if message.id > min_id]

        mgr.client.get_messages.side_effect = fetch_after_restart
        await mgr.start_task(task.task_id)
        assert mgr._tasks[task.task_id] is not first_runner
        await asyncio.wait_for(fetched_after_restart.wait(), timeout=1)
        assert mgr.get_task_status(task.task_id).status == "running"
        assert tracker.get_last_message_id(task.task_id) == 11
        assert tracker.get_task_progress(task.task_id).forwarded_count == 2
        assert attempts == [[10], [11], [11]]
        assert tracker.get_transfer(task.task_id) is None
    finally:
        await mgr.stop_task(task.task_id)


@pytest.mark.asyncio
async def test_invalid_configuration_does_not_change_memory_or_db(state):
    mgr = manager(state)
    cm = mgr.config_manager
    before = deepcopy(cm.get_config().to_dict())
    with pytest.raises(ValueError):
        await mgr.update_settings({"temp_dir": "/tmp/changed", "max_concurrent_tasks": "wrong"})
    assert cm.get_config().to_dict() == before
    assert cm.db.get_app_config()["temp_dir"] == before["temp_dir"]


def test_source_change_requires_explicit_checkpoint(state):
    mgr = manager(state)
    task = state[2]
    with pytest.raises(ValueError):
        mgr.update_task(replace(task, source_channel=-1003333333333))
    assert mgr.config_manager.get_task(task.task_id).source_channel == task.source_channel


@pytest.mark.parametrize("changes", [{"source_channel": -1002222222222}, {"min_delay": float("nan")}, {"max_delay": float("inf")}, {"enabled": "false"}, {"task_id": "../escape"}])
def test_invalid_tasks_rejected(state, changes):
    with pytest.raises(ValueError):
        validate_task(replace(state[2], **changes))


@pytest.mark.asyncio
async def test_retry_keeps_same_random_id_after_response_loss(state):
    cm, _, _ = state
    client = AsyncMock()
    client.get_input_entity.return_value = types.InputPeerChannel(2, 3)
    client.side_effect = [TimeoutError("response lost"), SimpleNamespace()]
    sender = ReliableSender(client, cm.db)
    media = types.InputMediaPhoto(types.InputPhoto(1, 2, b"ref"))
    with pytest.raises(TimeoutError):
        await sender.send("target", media, task_id="task", message_ids=[10])
    assert await sender.send("target", media, task_id="task", message_ids=[10])
    requests = [call.args[0] for call in client.call_args_list]
    assert requests[0].random_id == requests[1].random_id
    assert await sender.send("target", media, task_id="task", message_ids=[10])
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_duplicate_random_id_is_recorded_without_changing_identity(state):
    from telethon.errors import RandomIdDuplicateError
    cm, _, _ = state
    client = AsyncMock(side_effect=RandomIdDuplicateError(None))
    client.get_input_entity.return_value = types.InputPeerChannel(2, 3)
    sender = ReliableSender(client, cm.db)
    media = types.InputMediaPhoto(types.InputPhoto(1, 2, b"ref"))
    assert await sender.send("target", media, task_id="task", message_ids=[10])
    assert await sender.send("target", media, task_id="task", message_ids=[10])
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_manual_skip_album_does_not_skip_interleaved_message(state):
    cm, tracker, _ = state
    mgr = manager(state)
    tracker.begin_transfer("task", [1, 3], 2)
    tracker.update_transfer("task", {"ordered_ids": [1, 2, 3]})
    assert mgr.skip_transfer("task") == 1
    assert tracker.get_last_message_id("task") == 1
    assert 3 in tracker.completed_ids("task")
    assert 2 not in tracker.completed_ids("task")
