"""Main entry point for Telegram Forwarder."""
import argparse
import asyncio
import json
import os
import shutil
import sys
import signal
import tempfile

from .logger import setup_logging, get_logger
from .config_manager import ConfigManager
from .progress_tracker import ProgressTracker
from .telegram_client import TelegramClientWrapper
from .task_manager import TaskManager
from .bot import ForwarderBot
from .web_server import WebServer
from .models import ForwardTask
from .validators import validate_channel_id, validate_delay_range
from .temp_cleaner import cleanup_temp_dir
from .workspace import WorkspaceStore


logger = get_logger(__name__)


def _cleanup_stale_temp(config) -> None:
    """Remove stale files from the configured working directory once at startup."""
    temp_dir = getattr(config, 'temp_dir', 'temp') or 'temp'
    max_age = getattr(config, 'temp_max_age_hours', 24.0)
    WorkspaceStore(temp_dir).adopt_legacy_artwork([task.task_id for task in config.tasks])
    result = cleanup_temp_dir(temp_dir, max_age_hours=max_age)
    if result.get("removed"):
        logger.info(
            "Startup temp cleanup removed %s file(s), freed %.2f MB",
            result["removed"],
            result.get("freed_bytes", 0) / (1024 * 1024),
        )


async def login_flow(client: TelegramClientWrapper, phone: str) -> bool:
    """Interactive login flow."""
    await client.connect()

    if await client.is_authorized():
        logger.info("Already logged in")
        return True

    # Request code
    await client.login(phone)
    print(f"Verification code sent to {phone}")
    code = input("Enter verification code: ").strip()

    try:
        await client.login(phone, code)
        logger.info("Login successful")
        return True
    except ValueError as e:
        if "2FA" in str(e):
            password = input("Enter 2FA password: ").strip()
            await client.login(phone, code, password)
            logger.info("Login successful with 2FA")
            return True
        raise


async def cmd_login(args, config_manager: ConfigManager) -> None:
    """Handle login command."""
    config = config_manager.load_config()
    client = TelegramClientWrapper(config.api_id, config.api_hash)
    await login_flow(client, config.phone)
    await client.disconnect()


async def cmd_add_task(args, config_manager: ConfigManager) -> None:
    """Handle add-task command."""
    config_manager.load_config()

    # Validate inputs
    valid, err = validate_channel_id(args.source)
    if not valid:
        print(f"Invalid source channel: {err}")
        return

    valid, err = validate_channel_id(args.target)
    if not valid:
        print(f"Invalid target channel: {err}")
        return

    valid, err = validate_delay_range(args.min_delay, args.max_delay)
    if not valid:
        print(f"Invalid delay range: {err}")
        return

    if args.source_topic is not None and args.source_topic < 1:
        print("Invalid source topic: topic ID must be a positive integer")
        return

    task = ForwardTask(
        task_id=args.task_id,
        source_channel=args.source,
        target_channel=args.target,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        source_topic_id=args.source_topic,
        enabled=True
    )

    config_manager.add_task(task)
    print(f"Task '{args.task_id}' added successfully")


async def cmd_list_tasks(args, config_manager: ConfigManager,
                        progress_tracker: ProgressTracker) -> None:
    """Handle list command."""
    config_manager.load_config()
    progress_tracker.load_progress()

    config = config_manager.get_config()
    if not config or not config.tasks:
        print("No tasks configured")
        return

    print("\nConfigured Tasks:")
    print("-" * 60)
    for task in config.tasks:
        progress = progress_tracker.get_task_progress(task.task_id)
        status = "enabled" if task.enabled else "disabled"
        print(f"  [{task.task_id}] {status}")
        print(f"    Source: {task.source_channel}")
        print(f"    Target: {task.target_channel}")
        print(f"    Delay: {task.min_delay}s - {task.max_delay}s")
        print(f"    Forwarded: {progress.forwarded_count} messages")
        print()


async def cmd_start(args, config_manager: ConfigManager,
                   progress_tracker: ProgressTracker) -> None:
    """Handle start command."""
    config = config_manager.load_config()
    progress_tracker.load_progress()
    _cleanup_stale_temp(config)

    client = TelegramClientWrapper(config.api_id, config.api_hash)
    await client.connect()

    if not await client.is_authorized():
        print("Not logged in. Run 'login' command first.")
        await client.disconnect()
        return

    task_manager = TaskManager(
        client, config_manager, progress_tracker,
        temp_dir=getattr(config, 'temp_dir', 'temp') or 'temp'
    )

    try:
        if args.task_id:
            await task_manager.start_task(args.task_id)
        else:
            await task_manager.start_all_tasks()

        print("Forwarder running. Press Ctrl+C to stop.")

        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        await task_manager.stop_all_tasks()
    finally:
        await task_manager.stop_all_tasks()
        await client.disconnect()


async def cmd_delete_task(args, config_manager: ConfigManager,
                         progress_tracker: ProgressTracker) -> None:
    """Handle delete command."""
    config_manager.load_config()
    progress_tracker.load_progress()

    config_manager.remove_task(args.task_id)
    if args.delete_progress:
        progress_tracker.delete_progress(args.task_id)

    print(f"Task '{args.task_id}' deleted")


async def cmd_bot(args, config_manager: ConfigManager,
                 progress_tracker: ProgressTracker) -> None:
    """Handle bot command - start the management bot."""
    config = config_manager.load_config()
    progress_tracker.load_progress()

    if not config.bot_token:
        print("Error: bot_token not configured in config.json")
        return

    if not config.admin_ids:
        print("Error: admin_ids not configured in config.json")
        return

    _cleanup_stale_temp(config)

    # Start user client for forwarding
    user_client = TelegramClientWrapper(config.api_id, config.api_hash)
    await user_client.connect()

    if not await user_client.is_authorized():
        print("User not logged in. Run 'login' command first.")
        await user_client.disconnect()
        return

    # Start bot
    bot = ForwarderBot(
        bot_token=config.bot_token,
        admin_ids=config.admin_ids,
        config_manager=config_manager,
        progress_tracker=progress_tracker,
        user_client=user_client
    )

    # Start web server (optional, port from config or default 8080)
    web_port = getattr(config, 'web_port', 10082)
    web_server = None

    try:
        await bot.start()

        # Start web server after bot starts (need task_manager)
        web_server = WebServer(
            progress_tracker=progress_tracker,
            task_manager=bot._task_manager,
            port=web_port,
            web_password=getattr(config, 'web_password', '')
        )
        await web_server.start()

        print(f"Bot started. Web UI at http://127.0.0.1:{web_port}")
        print("Press Ctrl+C to stop.")
        await bot.run_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if web_server:
            await web_server.stop()
        await bot.stop()
        await user_client.disconnect()


async def cmd_migrate_db(args, config_manager: ConfigManager) -> None:
    """Migrate legacy JSON state into SQLite and print a verification report."""
    if args.dry_run:
        with tempfile.TemporaryDirectory(prefix="forwarder-migrate-") as temp_dir:
            source_dir = os.path.dirname(os.path.abspath(args.config))
            target_config = os.path.join(temp_dir, "config.json")
            for name in ("config.json", "progress.json", "progress_download.json"):
                source = os.path.join(source_dir, name)
                if os.path.exists(source):
                    shutil.copy2(source, os.path.join(temp_dir, name))
            for source in os.listdir(source_dir):
                if source.startswith("dedup_") and source.endswith(".json"):
                    shutil.copy2(os.path.join(source_dir, source), os.path.join(temp_dir, source))
            from .database import Database
            trial_db = Database(os.path.join(temp_dir, "forwarder.db"))
            imported = trial_db.ensure_legacy_migration(target_config)
            report = trial_db.verify_legacy(target_config)
        print(json.dumps({"dry_run": True, "imported": imported, "report": report}, ensure_ascii=False, indent=2))
    else:
        imported = config_manager.db.ensure_legacy_migration(args.config)
        report = config_manager.db.verify_legacy(args.config)
        print(json.dumps({"imported": imported, "report": report}, ensure_ascii=False, indent=2))
    if not report["all_tasks_match"] or not report["all_progress_match"]:
        raise RuntimeError("Database migration verification failed")


async def cmd_verify_db(args, config_manager: ConfigManager) -> None:
    """Verify SQLite state against legacy JSON files."""
    report = config_manager.db.verify_legacy(args.config)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_tasks_match"] or not report["all_progress_match"]:
        raise RuntimeError("Database verification failed")


async def cmd_export_json(args, config_manager: ConfigManager) -> None:
    """Export current SQLite state to a legacy-compatible directory."""
    output_dir = args.output_dir
    config_manager.db.export_legacy(output_dir)
    print(f"Exported database state to {output_dir}")

async def cmd_sync_json(args, config_manager: ConfigManager) -> None:
    """Synchronize the authoritative SQLite state into the configured JSON files."""
    backup_dir = config_manager.db.sync_legacy(args.config)
    print(f"Synchronized SQLite state to {args.config}; old JSON backed up to {backup_dir}")


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="Telegram Group/Channel Forwarder"
    )
    parser.add_argument(
        "--config", "-c",
        default="config/config.json",
        help="Path to config file"
    )
    parser.add_argument(
        "--log-level", "-l",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Login command
    subparsers.add_parser("login", help="Login to Telegram")

    # Add task command
    add_parser = subparsers.add_parser("add", help="Add a forwarding task")
    add_parser.add_argument("task_id", help="Unique task identifier")
    add_parser.add_argument("--source", "-s", type=int, required=True,
                          help="Source channel ID")
    add_parser.add_argument("--target", "-t", type=int, required=True,
                          help="Target channel ID")
    add_parser.add_argument("--source-topic", type=int, default=None,
                          help="Optional source forum topic root message ID")
    add_parser.add_argument("--min-delay", type=float, default=10.0,
                          help="Minimum delay between messages (seconds)")
    add_parser.add_argument("--max-delay", type=float, default=20.0,
                          help="Maximum delay between messages (seconds)")

    # List command
    subparsers.add_parser("list", help="List all tasks")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start forwarding")
    start_parser.add_argument("task_id", nargs="?", help="Task ID (optional)")

    # Delete command
    del_parser = subparsers.add_parser("delete", help="Delete a task")
    del_parser.add_argument("task_id", help="Task ID to delete")
    del_parser.add_argument("--delete-progress", "-p", action="store_true",
                          help="Also delete progress data")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize configuration")
    init_parser.add_argument("--api-id", type=int, required=True)
    init_parser.add_argument("--api-hash", required=True)
    init_parser.add_argument("--phone", required=True)
    init_parser.add_argument("--bot-token", default="", help="Bot token for management")
    init_parser.add_argument("--admin-id", type=int, action="append", dest="admin_ids",
                            default=[], help="Admin user ID (can specify multiple)")

    # Bot command
    subparsers.add_parser("bot", help="Start the management bot")

    migrate_parser = subparsers.add_parser("migrate-db", help="Migrate legacy JSON state into SQLite")
    migrate_parser.add_argument("--dry-run", action="store_true", help="Verify in a temporary database without writing project files")
    subparsers.add_parser("verify-db", help="Verify SQLite state against legacy JSON")
    export_parser = subparsers.add_parser("export-json", help="Export SQLite state to JSON files")
    export_parser.add_argument("output_dir", help="Output directory")
    subparsers.add_parser("sync-json", help="Synchronize SQLite state into the legacy JSON files")

    return parser


async def main() -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    setup_logging(args.log_level)

    config_manager = ConfigManager(args.config)
    progress_tracker = ProgressTracker(database=config_manager.db)

    if args.command == "init":
        if config_manager.db.get_app_config():
            raise ValueError("Configuration already exists; edit it through the management interface")
        from .models import AppConfig
        config = AppConfig(
            api_id=args.api_id,
            api_hash=args.api_hash,
            phone=args.phone,
            bot_token=getattr(args, 'bot_token', ''),
            admin_ids=getattr(args, 'admin_ids', []),
            tasks=[]
        )
        config_manager.save_config(config)
        print(f"Configuration created at {args.config}")
    elif args.command == "login":
        await cmd_login(args, config_manager)
    elif args.command == "add":
        await cmd_add_task(args, config_manager)
    elif args.command == "list":
        await cmd_list_tasks(args, config_manager, progress_tracker)
    elif args.command == "start":
        await cmd_start(args, config_manager, progress_tracker)
    elif args.command == "delete":
        await cmd_delete_task(args, config_manager, progress_tracker)
    elif args.command == "bot":
        await cmd_bot(args, config_manager, progress_tracker)
    elif args.command == "migrate-db":
        await cmd_migrate_db(args, config_manager)
    elif args.command == "verify-db":
        await cmd_verify_db(args, config_manager)
    elif args.command == "export-json":
        await cmd_export_json(args, config_manager)
    elif args.command == "sync-json":
        await cmd_sync_json(args, config_manager)
    else:
        parser.print_help()

async def _run_with_signals():
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
    asyncio.run(_run_with_signals())


if __name__ == "__main__":
    run()
