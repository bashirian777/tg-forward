"""Ownership, cancellation and command serialization regression checks."""
import asyncio
from dataclasses import replace
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_forwarder.runtime.bridge import RuntimeBridge
from tests.support import manager


from tg_forwarder.storage.passwords import verify_password


def test_plaintext_password_migration_redacts_history_and_preserves_tasks(state):
    import json
    from tg_forwarder.storage.config_store import ConfigManager
    cm, tracker, task = state
    tracker.record_forwarded(task.task_id, 12, 2)
    with cm.db.connection() as db:
        data = cm.db.get_app_config()
        data["web_password"] = "旧密码 pbkdf2:sha256:600000$literal"
        db.execute("UPDATE app_settings SET data=? WHERE id=1", (json.dumps(data),))
        db.execute("DELETE FROM metadata WHERE key='web_password_format'")
        db.execute("INSERT INTO config_snapshots(created_at,reason,data) VALUES('old','old',?)", (json.dumps(data),))
    cm.db.log_operation("old", after_data={"nested": {"web_password": data["web_password"]}})
    restarted = ConfigManager(cm.db.path)
    config = restarted.load_config()
    assert verify_password(config.web_password, data["web_password"])
    assert restarted.db.get_progress(task.task_id)["last_message_id"] == 12
    assert restarted.load_config().web_password == config.web_password
    with cm.db.connection() as db:
        for table, column in (("config_snapshots", "data"), ("operation_logs", "after_data")):
            assert all("web_password" not in row[0] for row in db.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"))


class Runtime:
    async def start_background(self):
        self.owner = threading.get_ident()
        self.stopped = False
        self.calls = 0

    async def invoke(self, operation, params, **context):
        assert threading.get_ident() == self.owner
        if operation == "slow":
            await asyncio.sleep(0.05)
        self.calls += 1
        return {"calls": self.calls, "items": []}

    async def shutdown(self):
        self.stopped = True


def test_bridge_owns_one_loop_and_returns_independent_snapshots():
    runtime = Runtime()
    bridge = RuntimeBridge(lambda: runtime).start()
    try:
        assert runtime.owner != threading.get_ident()
        first = bridge.call("query")
        first["items"].append("changed")
        assert bridge.call("query") == {"calls": 2, "items": []}
    finally:
        bridge.stop()
    assert runtime.stopped and not bridge.alive


def test_bridge_timeout_keeps_command_and_owner_can_observe_result():
    runtime = Runtime()
    bridge = RuntimeBridge(lambda: runtime, timeout=0.01).start()
    try:
        result = bridge.call("slow", token="owner")
        assert result["pending"]
        with pytest.raises(ValueError):
            bridge.result(result["operation_id"], "other")
        # A following request allows the original coroutine to finish naturally.
        bridge.timeout = 1
        bridge.call("slow")
        assert bridge.result(result["operation_id"], "owner")["result"]["calls"] == 1
    finally:
        bridge.stop()
    assert runtime.calls == 2


def test_bridge_start_failure_closes_service():
    runtime = Runtime()
    runtime.start_background = AsyncMock(side_effect=RuntimeError("startup failed"))
    with pytest.raises(RuntimeError, match="startup failed"):
        RuntimeBridge(lambda: runtime).start()
    assert runtime.stopped


@pytest.mark.asyncio
async def test_retry_holds_task_lock_through_stop_clear_and_restart(state):
    mgr = manager(state)
    entered, release = asyncio.Event(), asyncio.Event()
    events = []
    async def stopping(task_id):
        events.append("stop")
        entered.set()
        await release.wait()
    async def starting(task_id):
        events.append("start")
    mgr._stop_task = stopping
    mgr._start_task = starting
    mgr.is_active = lambda _: True
    mgr.clear_transfer = lambda _: events.append("clear")
    retry = asyncio.create_task(mgr.retry_transfer("task"))
    await entered.wait()
    other = asyncio.create_task(mgr.start_task("task"))
    await asyncio.sleep(0)
    assert events == ["stop"]
    release.set()
    await asyncio.gather(retry, other)
    assert events == ["stop", "clear", "start", "start"]


@pytest.mark.asyncio
async def test_start_and_settings_update_share_configuration_lock(state):
    mgr = manager(state)
    entered, release = asyncio.Event(), asyncio.Event()
    async def starting(_):
        entered.set()
        await release.wait()
        mgr.has_running_tasks = lambda: True
    mgr._start_task = starting
    start = asyncio.create_task(mgr.start_task("task"))
    await entered.wait()
    update = asyncio.create_task(mgr.update_settings({"download_workers": 8}))
    await asyncio.sleep(0)
    assert not update.done()
    release.set()
    await start
    with pytest.raises(ValueError):
        await update
    assert mgr.config_manager.get_config().download_workers == 4


def test_create_task_and_initial_checkpoint_are_committed_together(state):
    mgr = manager(state)
    mgr.create_task(replace(state[2], task_id="created"), start_id=99)
    assert mgr.task_snapshot("created")["progress"]["last_message_id"] == 99
    assert mgr.config_manager.db.list_logs(1)[0]["action"] == "create_task"


def test_bridge_shutdown_drains_accepted_call_and_rejects_new_work():
    runtime = Runtime()
    bridge = RuntimeBridge(lambda: runtime, timeout=0.01).start()
    assert bridge.call("slow", token="owner")["pending"]
    bridge.stop()
    assert runtime.calls == 1 and runtime.stopped
    with pytest.raises(ValueError, match="不可用"):
        bridge.call("query")


def test_bridge_propagates_business_timeout_without_making_pending_operation():
    runtime = Runtime()
    runtime.invoke = AsyncMock(side_effect=TimeoutError("business timeout"))
    bridge = RuntimeBridge(lambda: runtime).start()
    try:
        with pytest.raises(TimeoutError, match="business timeout"):
            bridge.call("query")
    finally:
        bridge.stop()


def test_authentication_timeout_returns_unavailable_and_does_not_poll_without_session():
    runtime = Runtime()
    async def slow(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {}
    runtime.invoke = slow
    bridge = RuntimeBridge(lambda: runtime, timeout=0.01).start()
    try:
        with pytest.raises(ValueError, match="认证服务响应超时"):
            bridge.call("auth.login")
        assert not bridge._pending
    finally:
        bridge.stop()
