"""Command-line entry points share .env deployment settings and SQLite state."""
import argparse
import asyncio
from getpass import getpass
import signal
import sqlite3
import json
import sys

from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.config.migration import DEPLOYMENT_KEYS, prepare_env, remove_deployment_fields
from tg_forwarder.storage.database import Database
from tg_forwarder.logging import get_logger, setup_logging
from tg_forwarder.tasks.models import ForwardTask
from tg_forwarder.config.paths import PROJECT_ROOT, project_path
from tg_forwarder.storage.progress_store import ProgressTracker
from tg_forwarder.runtime.service import connect_user, create_user_client
from tg_forwarder.telegram.session_guard import project_processes, session_guard
from tg_forwarder.config.startup import StartupConfig, StartupConfigurationError, read_startup_values
from tg_forwarder.tasks.manager import TaskManager
from tg_forwarder.runtime.cleanup import cleanup_temp_dir
from tg_forwarder.storage.workspace import WorkspaceStore

logger = get_logger(__name__)


def cleanup_stale_temp(config):
    WorkspaceStore(config.temp_dir).adopt_legacy_artwork([task.task_id for task in config.tasks])
    result = cleanup_temp_dir(config.temp_dir, config.temp_max_age_hours)
    if result["removed"]:
        logger.info("Startup cleanup removed %s files, freed %.2f MiB", result["removed"], result["freed_bytes"] / 1024**2)


async def login_flow(client, phone, *, relogin=False):
    await client.connect()
    if await client.is_authorized():
        if not relogin:
            await client.validate_account(phone)
            print("Telegram is already logged in")
            return
        await client.logout()
        await client.connect()
    await client.login(phone)
    code = input("Telegram verification code: ").strip()
    try:
        await client.login(phone, code)
    except ValueError as error:
        if "2FA" not in str(error):
            raise
        await client.login(phone, code, getpass("Telegram two-step verification password: "))
    await client.validate_account(phone)
    print("Telegram login completed")


async def run_login(startup, relogin):
    client = create_user_client(startup)
    try:
        await login_flow(client, startup.phone, relogin=relogin)
    finally:
        await client.disconnect()


async def run_forwarding(startup, manager, tracker, task_id):
    client = create_user_client(startup, database=manager.db)
    tasks = TaskManager(client, manager, tracker, temp_dir=manager.get_config().temp_dir)
    try:
        await connect_user(client, startup)
        cleanup_stale_temp(manager.get_config())
        if task_id:
            await tasks.start_task(task_id)
        else:
            await tasks.start_all_tasks()
        print("Forwarder running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()
    finally:
        await tasks.stop_all_tasks()
        await client.disconnect()


def create_parser():
    parser = argparse.ArgumentParser(description="Telegram Forwarder: .env deployment settings and SQLite runtime state")
    parser.add_argument("--env-file", default=str(PROJECT_ROOT / ".env"), help="Environment file (relative to project directory)")
    parser.add_argument("--log-level", "-l", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize SQLite defaults once, reading deployment settings from .env")
    login = commands.add_parser("login", help="Interactively log in to Telegram")
    login.add_argument("--relogin", action="store_true", help="Log out the old session and explicitly sign in to TG_PHONE")
    commands.add_parser("serve", help="Start Web, forwarding management and optional Bot")
    add = commands.add_parser("add", help="Add a forwarding task")
    add.add_argument("task_id")
    add.add_argument("--source", "-s", type=int, required=True)
    add.add_argument("--target", "-t", type=int, required=True)
    add.add_argument("--source-topic", type=int)
    add.add_argument("--require-video", action="store_true", help="Skip photo-only messages and albums; forward mixed albums containing video")
    add.add_argument("--include-topic-name", action="store_true", help="Include the source forum topic name after the caption prefix")
    add.add_argument("--min-delay", type=float, default=10.0)
    add.add_argument("--max-delay", type=float, default=20.0)
    commands.add_parser("list", help="List tasks and checkpoints")
    start = commands.add_parser("start", help="Run one task or all enabled tasks")
    start.add_argument("task_id", nargs="?")
    delete = commands.add_parser("delete", help="Delete a task and its state")
    delete.add_argument("task_id")
    commands.add_parser("verify-db", help="Check SQLite integrity and foreign keys")
    migration = commands.add_parser("migrate-env", help="Move existing SQLite deployment settings to .env")
    migration.add_argument("--db", help="Existing database to migrate (defaults to DB_PATH from environment or .env)")
    migration.add_argument("--prepare", action="store_true", help="Prepare .env only; finish migration after stopping the old service")
    return parser


def migrate_environment(args):
    env_file, values, _ = read_startup_values(args.env_file)
    if args.db is None and not values["DB_PATH"].strip():
        raise StartupConfigurationError("DB_PATH cannot be empty")
    db_path = project_path(args.db if args.db is not None else values["DB_PATH"])
    if args.prepare:
        prepare_env(db_path, env_file)
        print(f"Environment file prepared at {env_file}; database unchanged")
        return
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as existing:
        row = existing.execute("SELECT data FROM app_settings WHERE id=1").fetchone()
    already_migrated = row and not DEPLOYMENT_KEYS & json.loads(row[0]).keys()
    digest = None
    if not already_migrated:
        if any(project_processes({"bot", "serve", "start", "login"})):
            raise ValueError("The project's Telegram service is running; stop it before migrating")
        digest = prepare_env(db_path, env_file)
    startup = StartupConfig.load(env_file)
    if startup.db_path != db_path:
        raise StartupConfigurationError("DB_PATH must match the migration source database")
    with session_guard(startup.session_path):
        if already_migrated:
            print("Deployment settings already migrated; existing .env and SQLite preserved")
            return
        db = Database(db_path, create=False)
        remove_deployment_fields(db, digest)
        print(f"Deployment settings migrated to {env_file}; task and runtime state retained")


async def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_level)
    if args.command == "migrate-env":
        migrate_environment(args)
        return
    startup = StartupConfig.load(args.env_file)
    manager = ConfigManager(startup.db_path, create=args.command == "init")
    if args.command == "init":
        created = manager.initialize(startup.initial_password)
        print(f"SQLite initialized at {startup.db_path}" if created else "SQLite already initialized; existing configuration preserved")
        return
    manager.load_config()
    if args.command == "verify-db":
        report = manager.db.verify()
        if not report["ok"]:
            raise ValueError("SQLite integrity or foreign key check failed")
        print("SQLite integrity and foreign keys: ok")
        return
    tracker = ProgressTracker(database=manager.db)
    tracker.load_progress()
    if args.command == "add":
        task = ForwardTask(args.task_id, args.source, args.target, args.min_delay, args.max_delay, source_topic_id=args.source_topic, require_video=args.require_video, include_topic_name=args.include_topic_name)
        with session_guard(startup.session_path):
            tasks = TaskManager(create_user_client(startup, database=manager.db), manager, tracker, temp_dir=manager.get_config().temp_dir)
            tasks.create_task(task)
        print(f"Task '{task.task_id}' added")
    elif args.command == "list":
        for task in manager.get_config().tasks:
            progress = tracker.get_task_progress(task.task_id)
            print(f"[{task.task_id}] {'enabled' if task.enabled else 'disabled'}: {task.source_channel} -> {task.target_channel}, checkpoint={progress.last_message_id}, forwarded={progress.forwarded_count}")
    elif args.command == "delete":
        with session_guard(startup.session_path):
            tasks = TaskManager(create_user_client(startup, database=manager.db), manager, tracker, temp_dir=manager.get_config().temp_dir)
            await tasks.delete_task(args.task_id)
        print(f"Task '{args.task_id}' deleted")
    else:
        with session_guard(startup.session_path):
            if args.command == "login":
                await run_login(startup, args.relogin)
            elif args.command == "start":
                await run_forwarding(startup, manager, tracker, args.task_id)
            else:
                cleanup_stale_temp(manager.get_config())
                from tg_forwarder.runtime.server import serve
                serve(startup, manager, tracker)


async def run_with_signals():
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, current.cancel)
    try:
        await main()
    except asyncio.CancelledError:
        pass
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def run():
    try:
        asyncio.run(run_with_signals())
    except (StartupConfigurationError, ValueError, FileNotFoundError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
