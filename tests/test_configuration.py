"""Environment precedence, SQLite ownership, initialization and service lifecycle."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, Mock

from aiohttp.test_utils import TestClient, TestServer
import pytest

from src.config_manager import ConfigManager
from src.config_migration import prepare_env, remove_deployment_fields
from src.database import Database
from src.main import create_parser, main
from src.models import RuntimeConfig
from src.service import ForwarderService
from src.session_guard import session_guard
from src.startup_config import StartupConfig, StartupConfigurationError
from src.telegram_client import TelegramClientWrapper
from src.web_server import WebServer
from tests.test_controls import manager
from tests.test_integrity import state

VALUES = {"TG_API_ID": "12345", "TG_API_HASH": "a" * 32, "TG_PHONE": "+12345678901"}


def startup(tmp_path, **values):
    return StartupConfig.from_values(dict(VALUES, **values), project_root=tmp_path)


def env_file(tmp_path, **values):
    path = tmp_path / ".env"
    def quote(value):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    path.write_text("\n".join(name + "=" + quote(value) for name, value in dict(VALUES, **values).items()) + "\n")
    return path


def test_env_precedence_paths_and_literal_password(tmp_path, monkeypatch):
    path = env_file(tmp_path, WEB_PORT="12345", WEB_INITIAL_PASSWORD="中文 # '$HOME ${TG_PHONE}")
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = StartupConfig.load(path, environ={"WEB_PORT": "54321"}, project_root=tmp_path)
    assert config.web_port == 54321
    assert config.sources["WEB_PORT"] == "environment"
    assert config.sources["TG_API_HASH"] == ".env"
    assert config.sources["DB_PATH"] == "default"
    assert config.db_path == tmp_path / "config/forwarder.db"
    assert config.session_path == tmp_path / "data/sessions/forwarder.session"
    assert config.initial_password == "中文 # '$HOME ${TG_PHONE}"
    assert config.api_hash not in repr(config) and config.phone not in repr(config)
    public = json.dumps(config.public_info())
    assert config.api_hash not in public and config.initial_password not in public and config.phone not in public


@pytest.mark.parametrize("extra", ["TG_API_ID=12345\n", "TG_BOT_TOKEN='unterminated\n"])
def test_ambiguous_env_file_does_not_silently_disable_settings(tmp_path, extra):
    path = env_file(tmp_path)
    path.write_text(path.read_text() + extra)
    with pytest.raises(StartupConfigurationError, match="Duplicate|syntax"):
        StartupConfig.load(path, environ={}, project_root=tmp_path)


def test_session_suffix_normalizes_to_one_real_session(tmp_path):
    first = startup(tmp_path, SESSION_PATH="account")
    second = startup(tmp_path, SESSION_PATH="account.session")
    assert first.session_path == second.session_path
    with pytest.raises(StartupConfigurationError, match="differ"):
        startup(tmp_path, DB_PATH="account.session", SESSION_PATH="account")


def test_runtime_environment_variables_do_not_override_sqlite(tmp_path, state):
    path = env_file(tmp_path)
    StartupConfig.load(path, environ={"DOWNLOAD_WORKERS": "16", "WEB_AUTH_TTL_HOURS": "1"}, project_root=tmp_path)
    config = state[0].load_config()
    assert config.download_workers == 4 and config.web_auth_ttl_hours == 24


def test_empty_environment_value_is_not_replaced_by_dotenv(tmp_path):
    path = env_file(tmp_path)
    with pytest.raises(StartupConfigurationError, match="TG_API_ID"):
        StartupConfig.load(path, environ={"TG_API_ID": ""}, project_root=tmp_path)


@pytest.mark.parametrize("values,name", [
    ({"TG_API_ID": "-1"}, "TG_API_ID"), ({"TG_API_HASH": "secret-invalid"}, "TG_API_HASH"),
    ({"TG_PHONE": "123"}, "TG_PHONE"), ({"WEB_PORT": "65536"}, "WEB_PORT"),
    ({"TG_ADMIN_IDS": "123,,456"}, "TG_ADMIN_IDS"),
    ({"TG_BOT_TOKEN": "123:" + "b" * 30}, "TG_ADMIN_IDS"),
    ({"TG_PROXY_URL": "socks5://password@host"}, "TG_PROXY_URL"),
    ({"DB_PATH": "account.session", "SESSION_PATH": "account.session"}, "DB_PATH"),
])
def test_invalid_deployment_values_report_names_without_secrets(tmp_path, values, name):
    with pytest.raises(StartupConfigurationError, match=name) as error:
        startup(tmp_path, **values)
    assert "secret-invalid" not in str(error.value) and "password@host" not in str(error.value)


def test_proxy_and_admin_ids_are_parsed(tmp_path):
    config = startup(tmp_path, TG_BOT_TOKEN="123:" + "b" * 30, TG_ADMIN_IDS="1, 2,1",
        TG_PROXY_URL="socks5://user:p%23ss@localhost:1080")
    assert config.admin_ids == (1, 2)
    assert config.proxy == {"proxy_type": "socks5", "addr": "localhost", "port": 1080,
        "rdns": True, "username": "user", "password": "p#ss"}


def test_repeated_init_and_restart_preserve_sqlite_password_and_runtime(state):
    cm, tracker, _ = state
    tracker.record_forwarded("task", 25, 5)
    config = replace(cm.get_config(), web_password="后台新密码", download_workers=8)
    cm.save_app_config(config)
    revision = cm.db.revision()
    assert not cm.initialize("旧初始化密码")
    assert cm.db.revision() == revision
    restarted = ConfigManager(cm.db.path)
    assert restarted.load_config().web_password == "后台新密码"
    assert restarted.get_config().download_workers == 8
    assert restarted.db.get_progress("task")["last_message_id"] == 25
    assert not list(Path(cm.db.path).parent.glob("*.json"))


def test_missing_database_is_not_created_by_normal_start(tmp_path):
    missing = tmp_path / "wrong/forwarder.db"
    with pytest.raises(FileNotFoundError, match="DB_PATH"):
        ConfigManager(missing, create=False)
    assert not missing.parent.exists()


def test_sqlite_rejects_startup_fields(state):
    cm, _, _ = state
    before = cm.db.get_app_config()
    for method in (cm.db.update_app_config, cm.db.initialize_settings):
        with pytest.raises(ValueError, match="runtime"):
            method(dict(before, api_hash="must-not-be-saved"))
    assert cm.db.get_app_config() == before


def legacy_database(tmp_path):
    db = Database(tmp_path / "forwarder.db")
    cm = ConfigManager(database=db, project_root=tmp_path)
    cm.initialize("保留密码")
    from src.models import ForwardTask
    cm.add_task(ForwardTask("task", -1001, -1002, 0, 0))
    db.save_progress({"task_id": "task", "last_message_id": 88, "forwarded_count": 9})
    db.save_transfer("task", {"state": "interrupted", "message_ids": [89]})
    db.add_dedup_ids("task", ["file"])
    db.add_task_error("task", "test", "old error")
    old = dict(db.get_app_config(), api_id=12345, api_hash="a" * 32, phone="+12345678901",
        bot_token="", admin_ids=[], web_port=10082)
    with db.connection() as conn:
        conn.execute("UPDATE app_settings SET data=? WHERE id=1", (json.dumps(old),))
        conn.execute("INSERT INTO app_config VALUES(1,?,?)", (json.dumps(old), "old"))
        conn.execute("INSERT INTO config_snapshots(created_at,reason,data) VALUES(?,?,?)", ("old", "old", json.dumps(old)))
    db.log_operation("old", after_data={"settings": old})
    return db


def test_migration_preserves_state_and_removes_stale_credential_copies(tmp_path):
    db = legacy_database(tmp_path)
    path = tmp_path / ".env"
    digest = prepare_env(db.path, path, project_root=tmp_path, environ={})
    migrated = StartupConfig.load(path, environ={}, project_root=tmp_path)
    assert migrated.api_id == 12345
    assert migrated.session_path == tmp_path / "forwarder.session"  # Existing installations keep their original session.
    assert path.stat().st_mode & 0o777 == 0o600
    assert "api_hash" in db.get_app_config()  # prepare is read-only for SQLite
    assert remove_deployment_fields(db, digest)
    assert not remove_deployment_fields(db)
    config = ConfigManager(database=db, project_root=tmp_path).load_config()
    assert config.web_password == "保留密码"
    assert [task.task_id for task in config.tasks] == ["task"]
    assert db.get_progress("task")["last_message_id"] == 88
    assert db.get_transfer("task")["message_ids"] == [89]
    assert db.dedup_ids("task") == {"file"}
    assert db.task_error_summary("task")["count"] == 1
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_config").fetchone()[0] == 0
        for table, column in (("app_settings", "data"), ("config_snapshots", "data"), ("operation_logs", "after_data")):
            assert all("api_hash" not in row[0] for row in conn.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"))
    assert not list(tmp_path.rglob("*.json"))
    assert not (tmp_path / "backups").exists()
    assert db.verify()["ok"]


def test_migration_keeps_existing_env_and_rejects_conflicts(tmp_path):
    db = legacy_database(tmp_path)
    path = env_file(tmp_path, TG_API_ID="54321")
    original = path.read_bytes()
    before = db.get_app_config()
    with pytest.raises(StartupConfigurationError, match="TG_API_ID"):
        prepare_env(db.path, path, project_root=tmp_path)
    assert path.read_bytes() == original and db.get_app_config() == before


def test_migration_keeps_custom_session_and_converts_legacy_proxy(tmp_path):
    db = legacy_database(tmp_path)
    with db.connection() as conn:
        old = db.get_app_config()
        old["proxy"] = {"proxy_type": "socks5", "addr": "localhost", "port": 1080, "username": "user", "password": "p#ss"}
        conn.execute("UPDATE app_settings SET data=? WHERE id=1", (json.dumps(old),))
    path = env_file(tmp_path, SESSION_PATH="other-account.session")
    prepare_env(db.path, path, project_root=tmp_path)
    config = StartupConfig.load(path, environ={}, project_root=tmp_path)
    assert config.session_path == tmp_path / "other-account.session"
    assert config.proxy["password"] == "p#ss"


def test_migration_preserves_custom_env_values_and_detects_database_race(tmp_path):
    db = legacy_database(tmp_path)
    path = env_file(tmp_path, WEB_HOST="localhost", WEB_INITIAL_PASSWORD="独立初始密码")
    digest = prepare_env(db.path, path, project_root=tmp_path)
    assert StartupConfig.load(path, environ={}, project_root=tmp_path).initial_password == "独立初始密码"
    with db.connection() as conn:
        old = db.get_app_config()
        old["upload_workers"] = 8
        conn.execute("UPDATE app_settings SET data=? WHERE id=1", (json.dumps(old),))
    with pytest.raises(ValueError, match="changed"):
        remove_deployment_fields(db, digest)
    assert "api_hash" in db.get_app_config()


@pytest.mark.asyncio
async def test_removed_json_routes_and_readonly_deployment_fields(state, tmp_path):
    cm, _, _ = state
    mgr = manager(state)
    config = startup(tmp_path)
    server = WebServer(mgr.progress_tracker, mgr, startup=config)
    async with TestClient(TestServer(server.create_app())) as client:
        for route in ("/api/config/sync-json", "/api/config/backup"):
            assert (await client.post(route)).status == 404
        response = await client.get("/api/deployment")
        assert response.status == 200
        body = await response.text()
        assert config.api_hash not in body and config.phone not in body
        before = cm.db.get_app_config()
        for data in ({"web_port": 1234}, {"api_id": 4321}, {"bot_token": "invalid"}):
            assert (await client.put("/api/config", json=data)).status == 400
        assert cm.db.get_app_config() == before
        assert (await client.get("/api/config")).status == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["network", "login", "account"])
async def test_web_stays_available_when_telegram_cannot_start(state, tmp_path, failure):
    cm, tracker, _ = state
    service = ForwarderService(replace(startup(tmp_path), web_port=0), cm, tracker)
    service.client.connect = AsyncMock(side_effect=ConnectionError() if failure == "network" else None)
    service.client.is_authorized = AsyncMock(return_value=failure != "login")
    service.client.validate_account = AsyncMock(side_effect=ValueError("会话与 TG_PHONE 不一致") if failure == "account" else None)
    runner = asyncio.create_task(service.run())
    try:
        for _ in range(200):
            if service.web._runner and service.web._runner.sites and service.client.connection_status["state"] in ("error", "login_required"):
                break
            await asyncio.sleep(0.001)
        assert not runner.done()
        site = next(iter(service.web._runner.sites))
        port = site._server.sockets[0].getsockname()[1]
        from aiohttp import ClientSession
        async with ClientSession() as client:
            async with client.get(f"http://127.0.0.1:{port}/api/deployment") as response:
                assert response.status == 200
                body = await response.json()
                assert body["services"]["telegram"]["state"] != "ready"
            async with client.post(f"http://127.0.0.1:{port}/api/tasks/task/action", json={"action": "start"}) as response:
                assert response.status == 400
        assert not service.task_manager.has_running_tasks()
    finally:
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
    assert all(worker.done() for worker in service._workers)


@pytest.mark.asyncio
async def test_bot_failure_keeps_web_and_uses_shared_task_manager(state, tmp_path):
    cm, tracker, _ = state
    config = startup(tmp_path, TG_BOT_TOKEN="123:" + "b" * 30, TG_ADMIN_IDS="1")
    service = ForwarderService(config, cm, tracker)
    assert service.bot._task_manager is service.task_manager
    service.bot.start = AsyncMock(side_effect=RuntimeError(config.bot_token))
    service.bot.stop = AsyncMock()
    loop = asyncio.create_task(service._bot_loop())
    try:
        for _ in range(50):
            if service.bot_status["state"] == "error":
                break
            await asyncio.sleep(0)
        assert service.bot_status["state"] == "error"
        assert config.bot_token not in json.dumps(service.status())
        async with TestClient(TestServer(service.web.create_app())) as client:
            assert (await client.get("/api/tasks")).status == 200
    finally:
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop


@pytest.mark.asyncio
async def test_mismatched_phone_cannot_reuse_existing_session(tmp_path):
    client = TelegramClientWrapper(12345, "a" * 32)
    client._client = AsyncMock()
    client._client.get_me.return_value = type("Me", (), {"phone": "19999999999"})()
    with pytest.raises(ValueError, match="TG_PHONE"):
        await client.validate_account("+12345678901")
    client._client.get_me.return_value.phone = "12345678901"
    await client.validate_account("+12345678901")


@pytest.mark.asyncio
async def test_nested_session_directory_is_created_before_telethon(tmp_path, monkeypatch):
    config = startup(tmp_path)
    client = TelegramClientWrapper(config.api_id, config.api_hash, session_name=str(config.session_path))
    telegram = AsyncMock()
    telegram.is_connected = Mock(return_value=True)
    def create_telegram(path, *args, **kwargs):
        assert path == str(config.session_path)
        assert Path(path).parent.is_dir()
        return telegram
    monkeypatch.setattr("src.telegram_client.TelegramClient", create_telegram)
    assert not config.session_path.parent.exists()
    assert await client.connect()
    await client.disconnect()
    telegram.connect.assert_awaited_once()
    telegram.disconnect.assert_awaited_once()


def test_session_guard_prevents_parallel_use(tmp_path):
    with session_guard(tmp_path / "session", project_root=tmp_path):
        with pytest.raises(ValueError, match="in use"):
            with session_guard(tmp_path / "session", project_root=tmp_path):
                pytest.fail("Session lock was not exclusive")


@pytest.mark.asyncio
async def test_repeated_migration_locks_the_configured_nested_session(tmp_path, monkeypatch):
    db_path = tmp_path / "config/forwarder.db"
    cm = ConfigManager(db_path, create=True, project_root=tmp_path)
    cm.initialize("保留密码")
    expected = tmp_path / "data/sessions/forwarder.session"
    env = env_file(tmp_path, DB_PATH=str(db_path), SESSION_PATH=str(expected))
    monkeypatch.setattr("src.startup_config.os.environ", {})
    captured = []
    @contextmanager
    def isolated_guard(path):
        captured.append(path)
        with session_guard(path, project_root=tmp_path):
            yield
    monkeypatch.setattr("src.main.session_guard", isolated_guard)
    before = cm.db.get_app_config()
    await main(["--env-file", str(env), "migrate-env", "--db", str(db_path)])
    assert captured == [expected]
    assert Path(str(expected) + ".lock").exists()
    assert not (tmp_path / "forwarder.session.lock").exists()
    assert cm.db.get_app_config() == before


def test_removed_json_commands_are_rejected():
    parser = create_parser()
    for command in ("sync-json", "export-json", "migrate-db"):
        with pytest.raises(SystemExit):
            parser.parse_args([command])
    with pytest.raises(SystemExit):
        parser.parse_args(["--config", "config/config.json", "serve"])


@pytest.mark.asyncio
async def test_cli_init_reads_env_once_and_verify_uses_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.PROJECT_ROOT", tmp_path)
    env = env_file(tmp_path, DB_PATH=str(tmp_path / "forwarder.db"), WEB_INITIAL_PASSWORD="初始中文密码")
    monkeypatch.setattr("src.startup_config.os.environ", {})
    await main(["--env-file", str(env), "init"])
    cm = ConfigManager(tmp_path / "forwarder.db")
    config = cm.load_config()
    assert config.web_password == "初始中文密码"
    cm.save_app_config(replace(config, web_password="后台修改"))
    await main(["--env-file", str(env), "init"])
    await main(["--env-file", str(env), "verify-db"])
    assert cm.load_config().web_password == "后台修改"
    assert not list(tmp_path.rglob("*.json"))
