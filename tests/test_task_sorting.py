"""Persisted task order, atomic moves and recent-forwarding list behavior."""
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3

import pytest

from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.storage.database import Database
from tg_forwarder.storage.progress_store import ProgressTracker
from tests.http_support import http_client, login
from tests.support import manager


@pytest.fixture
def ordered_state(state):
    cm, tracker, task = state
    for task_id in ("alpha", "zulu"):
        cm.add_task(replace(task, task_id=task_id))
    return state


def ids(tasks):
    return [task["task_id"] for task in tasks]


def test_existing_database_migrates_in_current_id_order_only_once(tmp_path, state):
    _, _, task = state
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE tasks(task_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
        for task_id in ("zulu", "alpha", "task"):
            db.execute("INSERT INTO tasks VALUES(?,?,?)", (task_id,
                json.dumps(replace(task, task_id=task_id).to_dict()), "old"))
    database = Database(str(path))
    assert ids(database.list_tasks()) == ["alpha", "task", "zulu"]
    database.move_task("task", "up")
    assert ids(Database(str(path)).list_tasks()) == ["task", "alpha", "zulu"]
    assert database.get_metadata("task_sort_mode") == "manual"


def test_moves_append_edit_delete_and_restart_preserve_state(ordered_state, tmp_path):
    cm, tracker, task = ordered_state
    tracker.record_forwarded("task", 12, 3)
    cm.db.add_dedup_ids("task", ["photo_1"])
    mgr = manager(ordered_state)
    before = deepcopy(mgr.task_snapshot("task"))
    config_revision = cm.revision
    mgr._statuses["task"] = "running"
    mgr.move_task("task", "down")
    assert ids(mgr.task_snapshots()) == ["alpha", "task", "zulu"]
    assert mgr.task_snapshot("task")["status"] == "running"
    after = mgr.task_snapshot("task")
    after["status"] = before["status"]
    assert after == before and cm.revision == config_revision
    assert cm.db.dedup_ids("task") == {"photo_1"}
    mgr.move_task("alpha", "up")  # boundary is a successful no-op
    mgr.move_task("zulu", "down")
    assert ids(mgr.task_snapshots()) == ["alpha", "task", "zulu"]
    cm.update_task(replace(task, note="edited"))
    cm.add_task(replace(task, task_id="aardvark"))
    cm.remove_task("alpha")
    assert ids(cm.db.list_tasks()) == ["task", "zulu", "aardvark"]
    reloaded = ConfigManager(cm.db.path, project_root=tmp_path)
    reloaded.load_config()
    assert [task.task_id for task in reloaded.get_config().tasks] == ["task", "zulu", "aardvark"]
    assert ProgressTracker(database=reloaded.db).load_progress()["task"].forwarded_count == 3


def test_partial_swap_failure_rolls_back_database_and_memory(ordered_state):
    cm, _, _ = ordered_state
    mgr = manager(ordered_state)
    before = mgr.task_snapshots()
    with cm.db.connection() as db:
        db.execute("""CREATE TRIGGER reject_second_position BEFORE UPDATE OF sort_order ON tasks
            WHEN OLD.task_id='alpha' AND NEW.sort_order != OLD.sort_order
            BEGIN SELECT RAISE(ABORT, 'position failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="position failure"):
        mgr.move_task("task", "down")
    assert mgr.task_snapshots() == before
    assert ids(cm.db.list_tasks()) == ids(before)


def test_recent_sort_is_stable_uses_actual_times_and_preserves_manual_order(ordered_state, tmp_path):
    cm, tracker, _ = ordered_state
    mgr = manager(ordered_state)
    mgr.move_task("zulu", "up")
    times = {"task": "2026-01-01T10:00:00+00:00", "zulu": "2026-01-01T12:00:00+02:00",
        "alpha": "2026-01-01T11:00:00+00:00"}
    for task_id, value in times.items():
        tracker.get_task_progress(task_id).last_forward_time = value
    tracker.save_progress()
    mgr.set_task_sort_mode("recent")
    assert ids(mgr.tasks_view()["tasks"]) == ["alpha", "task", "zulu"]
    assert mgr.tasks_view()["sort_mode"] == "recent"
    with pytest.raises(ValueError, match="手动顺序"):
        mgr.move_task("alpha", "up")
    reloaded = ConfigManager(cm.db.path, project_root=tmp_path)
    reloaded.load_config()
    restarted_tracker = ProgressTracker(database=reloaded.db)
    restarted_tracker.load_progress()
    restarted = manager((reloaded, restarted_tracker, ordered_state[2]))
    assert restarted.tasks_view() == mgr.tasks_view()
    tracker.get_task_progress("alpha").last_forward_time = ""
    assert ids(mgr.task_snapshots()) == ["task", "zulu", "alpha"]
    tracker.get_task_progress("zulu").last_forward_time = "2026-01-01T13:00:00Z"
    assert ids(mgr.task_snapshots()) == ["zulu", "task", "alpha"]
    mgr.set_task_sort_mode("manual")
    assert ids(mgr.task_snapshots()) == ["task", "zulu", "alpha"]
    assert ids(cm.db.list_tasks()) == ["task", "zulu", "alpha"]


@pytest.mark.parametrize("path,payload", [
    ("/api/task-order", {"sort_mode": "oldest"}),
    ("/api/task-order", {"sort_mode": True}),
    ("/api/task-order", {"sort_mode": []}),
    ("/api/tasks/task/move", {"direction": "left"}),
    ("/api/tasks/task/move", {"direction": None}),
    ("/api/tasks/task/move", {"direction": {}}),
])
def test_invalid_sort_requests_do_not_change_state(ordered_state, tmp_path, path, payload):
    cm, _, _ = ordered_state
    with http_client(ordered_state, tmp_path) as (client, _):
        headers = login(client)
        before = client.get("/api/tasks?view=1").json
        response = client.put(path, headers=headers, json=payload) if path == "/api/task-order" else client.post(path, headers=headers, json=payload)
        assert response.status_code == 400
        assert response.json["error"] == "invalid_input"
        assert client.get("/api/tasks?view=1").json == before
    assert cm.db.get_metadata("task_sort_mode") == "manual"


def test_http_sorting_keeps_array_contract_checks_auth_and_accepts_order_task_id(ordered_state, tmp_path):
    cm, _, task = ordered_state
    cm.add_task(replace(task, task_id="order"))
    with http_client(ordered_state, tmp_path, password="secret") as (client, _):
        assert client.put("/api/task-order", json={"sort_mode": "recent"}).status_code == 401
        headers = login(client, "secret")
        assert client.post("/api/tasks/task/move", json={"direction": "down"}).status_code == 403
        assert client.post("/api/tasks/task/move", headers=headers, json={"direction": "down"}).status_code == 200
        assert ids(client.get("/api/tasks").json) == ["alpha", "task", "zulu", "order"]
        view = client.get("/api/tasks?view=1").json
        assert view["sort_mode"] == "manual" and ids(view["tasks"]) == ["alpha", "task", "zulu", "order"]
        assert client.post("/api/tasks/missing/move", headers=headers, json={"direction": "up"}).status_code == 404
        assert client.put("/api/task-order", headers=headers, json={"sort_mode": "recent"}).status_code == 200
        assert client.get("/api/tasks?view=1").json["sort_mode"] == "recent"
        assert client.post("/api/tasks/task/move", headers=headers, json={"direction": "up"}).status_code == 400
        snapshot = client.get("/api/tasks/order").json
        assert client.put("/api/tasks/order", headers=headers,
            json=dict(snapshot["config"], revision=snapshot["revision"], note="editable")).status_code == 200
        assert client.get("/api/tasks/order").json["config"]["note"] == "editable"
