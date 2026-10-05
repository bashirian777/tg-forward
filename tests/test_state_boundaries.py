"""Business transitions are guarded and commit as a single unit."""
from dataclasses import replace
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tg_forwarder.tasks.manager import TaskManager


def task_manager(state):
    config, progress, _ = state
    return TaskManager(SimpleNamespace(set_progress_tracker=Mock()), config, progress,
        temp_dir=config.get_config().temp_dir)


def pending_state(state):
    config, progress, task = state
    progress.record_forwarded(task.task_id, 100, 5)
    progress.complete_group(task.task_id, [102], "receipt", ordered_ids=[101, 102])
    progress.begin_transfer(task.task_id, [101], 1)
    config.db.save_intent(task.task_id, "pending", {"message_ids": [101], "random_ids": [42], "sent": False})
    config.db.add_dedup_ids(task.task_id, ["media"])


@pytest.mark.parametrize("entry", ["config", "database"])
def test_source_change_cannot_bypass_reset_rule(state, entry):
    config, _, task = state
    pending_state(state)
    changed = replace(task, source_channel=-1003333333333)
    with pytest.raises(ValueError, match="source_reset"):
        if entry == "config":
            config.update_task(changed)
        else:
            config.db.save_task(changed.to_dict())
    assert config.db.get_task(task.task_id) == task.to_dict()
    assert config.db.get_progress(task.task_id)["last_message_id"] == 100
    assert config.db.get_intent(task.task_id, "pending")


@pytest.mark.parametrize("clear_dedup", [False, True])
def test_source_change_atomically_replaces_related_state(state, clear_dedup):
    config, progress, task = state
    pending_state(state)
    manager = task_manager(state)
    changed = replace(task, source_channel=-1003333333333)
    manager.update_task(changed, source_reset={"last_message_id": 200, "clear_dedup": clear_dedup})
    assert config.get_task(task.task_id) == changed
    assert progress.get_last_message_id(task.task_id) == 200
    assert progress.get_task_progress(task.task_id).forwarded_count == 0
    assert not config.db.completed_ids(task.task_id)
    assert config.db.get_intent(task.task_id, "pending") is None
    assert progress.get_transfer(task.task_id) is None
    assert config.db.dedup_ids(task.task_id) == (set() if clear_dedup else {"media"})


def test_checkpoint_failure_preserves_database_and_memory(state):
    config, progress, task = state
    pending_state(state)
    manager = task_manager(state)
    with config.db.connection() as connection:
        connection.execute("""CREATE TRIGGER fail_checkpoint BEFORE INSERT ON task_progress
            BEGIN SELECT RAISE(ABORT, 'simulated checkpoint write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        manager.set_progress(task.task_id, 200)
    assert config.db.get_progress(task.task_id)["last_message_id"] == 100
    assert progress.get_last_message_id(task.task_id) == 100
    assert progress.get_task_progress(task.task_id).forwarded_count == 5
    assert config.db.completed_ids(task.task_id) == {102}
    assert config.db.get_intent(task.task_id, "pending")
    assert progress.get_transfer(task.task_id)["message_ids"] == [101]
    assert config.db.get_transfer(task.task_id)["message_ids"] == [101]


def test_checkpoint_success_preserves_count_and_clears_pending_state(state):
    config, progress, task = state
    pending_state(state)
    manager = task_manager(state)
    result = manager.set_progress(task.task_id, 200)
    assert result.last_message_id == 200 and result.forwarded_count == 5
    assert progress.get_transfer(task.task_id) is None
    assert not config.db.completed_ids(task.task_id)
    assert config.db.get_intent(task.task_id, "pending") is None
    assert config.db.dedup_ids(task.task_id) == {"media"}


def test_stale_task_form_gets_conflict_before_source_reset_validation(state, tmp_path):
    from tests.http_support import http_client, login
    task = state[2]
    with http_client(state, tmp_path) as (client, _):
        headers = login(client)
        initial = client.get("/api/tasks/task").json
        changed = dict(initial["config"], source_topic_id=23, revision=initial["revision"],
            source_reset={"last_message_id": 123, "clear_dedup": True})
        assert client.put("/api/tasks/task", headers=headers, json=changed).status_code == 200
        stale = dict(initial["config"], note="my edit", revision=initial["revision"])
        response = client.put("/api/tasks/task", headers=headers, json=stale)
        assert response.status_code == 409
        assert response.json["error"] == "configuration_conflict"
        latest = client.get("/api/tasks/task").json
        assert latest["config"]["source_topic_id"] == 23
        assert latest["progress"]["last_message_id"] == 123
