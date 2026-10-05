"""Management queries isolate snapshots and settings never expose passwords."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tg_forwarder.runtime.operations import ManagementOperations
from tg_forwarder.storage.passwords import verify_password
from tg_forwarder.tasks.errors import TaskNotFound
from tg_forwarder.tasks.queries import ManagementQueries
from tg_forwarder.tasks.settings import RuntimeSettings
from tests.support import manager


@pytest.fixture
def shared_queries(tmp_path):
    # Return cached mutable objects to expose accidental aliasing at the boundary.
    payload = {"details": {"labels": ["original"]}}
    task = SimpleNamespace(task_id="task")
    config = SimpleNamespace(tasks=[task], web_password="secret",
        settings_dict=lambda: dict(payload, web_password="secret"))
    database = SimpleNamespace(path=str(tmp_path / "forwarder.db"),
        dedup_count=lambda _: 2, list_dedup=lambda *_: [payload],
        list_logs=lambda *_: [payload])
    configs = SimpleNamespace(get_config=lambda: config, get_task=lambda _: task,
        task_revision=lambda _: 3, revision=4, db=database)
    progress = SimpleNamespace(
        get_task_progress=lambda _: SimpleNamespace(to_dict=lambda: payload),
        get_transfer=lambda _: payload, get_all_transfers=lambda: [payload],
        get_task_error_summary=lambda _: payload, get_task_errors=lambda *_: [payload])
    status = SimpleNamespace(task_id="task", to_dict=lambda: payload)
    queries = ManagementQueries(configs, progress, lambda _: status,
        {"task": SimpleNamespace(get_stats=lambda: payload)}, RuntimeSettings(configs))
    return queries, payload


@pytest.mark.parametrize("method,args,path", [
    ("task_snapshot", ("task",), ()),
    ("task_snapshots", (), (0,)),
    ("config_snapshot", (), ()),
    ("progress_snapshot", ("task",), ()),
    ("get_transfer", ("task",), ()),
    ("get_all_transfers", (), (0,)),
    ("get_dedup_stats", ("task",), ()),
    ("dedup_snapshot", ("task", 7), ("stats",)),
    ("dedup_snapshot", ("task", 7), ("records", 0)),
    ("get_task_error_summary", ("task",), ()),
    ("get_task_errors", ("task", 7), (0,)),
    ("errors_snapshot", ("task", 7), ("summary",)),
    ("errors_snapshot", ("task", 7), ("errors", 0)),
    ("get_logs", (7,), (0,)),
])
def test_query_snapshots_do_not_share_nested_state(shared_queries, method, args, path):
    queries, live = shared_queries
    read = getattr(queries, method)
    first, second = read(*args), read(*args)
    original = deepcopy(second)
    selected = first
    for key in path:
        selected = selected[key]
    selected["details"]["labels"].append("caller edit")
    assert live["details"]["labels"] == ["original"]
    assert second == original
    assert read(*args) == original
    retained = deepcopy(first)
    live["details"]["labels"].append("runtime edit")
    assert first == retained and second == original
    assert read(*args) != original


def test_query_missing_task_and_unloaded_task_list(shared_queries):
    queries, _ = shared_queries
    queries.config_manager.get_task = lambda _: None
    with pytest.raises(TaskNotFound):
        queries.task_snapshot("missing")
    queries.config_manager.get_config = lambda: None
    assert queries.list_tasks() == []


@pytest.mark.parametrize("operation,params,method,args", [
    ("logs", {"limit": 7}, "get_logs", (7,)),
    ("progress", {"task_id": "task"}, "progress_snapshot", ("task",)),
    ("dedup", {"task_id": "task", "limit": 7}, "dedup_snapshot", ("task", 7)),
    ("errors", {"task_id": "task", "limit": 7}, "errors_snapshot", ("task", 7)),
    ("transfers", {}, "get_all_transfers", ()),
])
async def test_queries_work_without_storage_objects_on_facade(operation, params, method, args):
    facade = Mock(spec_set=["require_task", method])
    result = {"items": ["snapshot"]}
    getattr(facade, method).return_value = result
    operations = ManagementOperations(None, facade, lambda: {})
    assert await operations.invoke(operation, params) == result
    getattr(facade, method).assert_called_once_with(*args)


@pytest.mark.parametrize("password", ["new secret password", ""])
async def test_settings_snapshot_and_audit_never_expose_password(state, monkeypatch, password):
    cm, _, _ = state
    old_password = "old secret password"
    cm.save_app_config(replace(cm.get_config(), web_password=old_password))
    mgr = manager(state)
    old_digest = cm.get_config().web_password
    monkeypatch.setattr(mgr, "has_running_tasks", lambda: True)
    refresh = Mock()
    monkeypatch.setattr(mgr, "refresh_runtime_limits", refresh)
    audit = Mock(wraps=cm.db.log_operation)
    monkeypatch.setattr(cm.db, "log_operation", audit)
    snapshot = await mgr.update_settings({"web_password": password,
        "web_auth_ttl_hours": 1, "revision": cm.revision})
    new_digest = cm.get_config().web_password
    assert verify_password(new_digest, password or old_password)
    assert (new_digest != old_digest) is bool(password)
    assert snapshot["web_password_configured"] and snapshot["web_auth_ttl_hours"] == 1
    assert snapshot["revision"] == cm.revision
    refresh.assert_not_called()
    audit.assert_called_once()
    audited = audit.call_args.kwargs["after_data"]
    serialized = json.dumps([snapshot, audited, cm.db.list_logs()], ensure_ascii=False)
    assert '"web_password"' not in serialized
    for secret in (old_password, old_digest, new_digest, password):
        if secret:
            assert secret not in serialized
    with cm.db.connection() as connection:
        histories = connection.execute("SELECT data FROM config_snapshots").fetchall()
    assert all('"web_password"' not in row[0] for row in histories)


async def test_reload_queries_use_fresh_dedup_records(state):
    cm, _, _ = state
    mgr = manager(state)
    mgr._dedup_trackers["task"] = SimpleNamespace(get_stats=lambda: {"total_tracked": 99})
    cm.db.add_dedup_ids("task", ["persisted"])
    assert mgr.dedup_snapshot("task")["stats"]["total_tracked"] == 99
    await mgr.reload_runtime()
    assert mgr.dedup_snapshot("task")["stats"]["total_tracked"] == 1
    mgr._dedup_trackers["task"] = SimpleNamespace(get_stats=lambda: {"total_tracked": 2})
    assert mgr.dedup_snapshot("task")["stats"]["total_tracked"] == 2
