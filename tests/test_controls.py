"""Task controls, validation, and transport retry regression checks."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from telethon import types
from tg_forwarder.forwarding.engine import Forwarder
from tg_forwarder.tasks.manager import TaskManager
from tg_forwarder.telegram.sender import ReliableSender
from tg_forwarder.tasks.validation import validate_task
from tests.test_integrity import state


def manager(state):
    cm, tracker, _ = state
    return TaskManager(SimpleNamespace(set_progress_tracker=Mock(), ensure_ready=AsyncMock()), cm, tracker, temp_dir=cm.get_config().temp_dir)


@pytest.mark.asyncio
async def test_resume_stopped_task_rejected(state):
    mgr = manager(state)
    with pytest.raises(ValueError):
        await mgr.resume_task("task")
    assert mgr.get_task_status("task").status == "stopped"


@pytest.mark.asyncio
async def test_paused_queued_task_does_not_send(state):
    cm, tracker, task = state
    semaphore = asyncio.Semaphore(0)
    handler = SimpleNamespace(is_media_message=lambda m: True, forward_message_group=AsyncMock())
    client = SimpleNamespace(get_messages=AsyncMock(return_value=[SimpleNamespace(id=1, grouped_id=None)]))
    engine = Forwarder(client, handler, tracker, semaphore)
    runner = asyncio.create_task(engine.run_task(task))
    for _ in range(20):
        if semaphore._waiters:
            break
        await asyncio.sleep(0)
    engine.pause()
    semaphore.release()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    handler.forward_message_group.assert_not_awaited()
    engine.stop()
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner


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
