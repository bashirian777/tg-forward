"""Web, Bot and forwarding share one task manager and one Telegram session."""
import asyncio
import logging

from tg_forwarder.bot.app import ForwarderBot
from tg_forwarder.tasks.manager import TaskManager
from tg_forwarder.telegram.client import TelegramClientWrapper, TelegramSessionError
from tg_forwarder.web.auth import AuthSessions
from .operations import ManagementOperations

logger = logging.getLogger(__name__)


def create_user_client(startup):
    return TelegramClientWrapper(startup.api_id, startup.api_hash,
        session_name=str(startup.session_path), proxy=startup.proxy)


async def connect_user(client, startup):
    await client.connect()
    if not await client.is_authorized():
        raise TelegramSessionError("Telegram 尚未登录，请停止服务后执行 login")
    await client.validate_account(startup.phone)
    client.connection_status = {"state": "ready", "message": "Telegram 已连接"}


class ForwarderService:
    def __init__(self, startup, config_manager, progress_tracker):
        self.startup = startup
        self.client = create_user_client(startup)
        self.task_manager = TaskManager(self.client, config_manager, progress_tracker,
            temp_dir=config_manager.get_config().temp_dir)
        self.bot = ForwarderBot(startup, self.task_manager) if startup.bot_token else None
        self.bot_status = {"state": "connecting" if self.bot else "disabled",
            "message": "Bot 正在连接" if self.bot else "未启用 Bot"}
        self._workers = []
        self.operations = ManagementOperations(startup, self.task_manager, self.status)

        self.auth = AuthSessions(config_manager.get_config)

    async def invoke(self, operation, params, *, token=None, csrf=None, write=False):
        if operation == "auth.info":
            return self.auth.info(token)
        if operation == "auth.login":
            return self.auth.login(params.get("password", ""), params.get("address", "local"))
        self.auth.authorize(token, csrf, write)
        if operation == "auth.logout":
            return self.auth.logout(token)
        if operation == "auth.check":
            return {"success": True}
        result = await self.operations.invoke(operation, params)
        # Reloads from Bot and CLI are caught by password_version on each request.
        return result

    async def start_background(self):
        self._workers = [asyncio.create_task(self._user_loop()), asyncio.create_task(self._cleanup_loop())]
        if self.bot:
            self._workers.append(asyncio.create_task(self._bot_loop()))

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(600)
            try:
                self.task_manager.cleanup_files(expired_only=True)
            except Exception:
                logger.exception("Periodic workspace cleanup failed")

    async def shutdown(self):
        self.client.connection_status = {"state": "stopping", "message": "服务正在停止"}
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        await self.task_manager.stop_all_tasks()
        if self.bot:
            await self.bot.stop()
        await self.client.disconnect()

    def status(self):
        return {"telegram": dict(self.client.connection_status), "bot": dict(self.bot_status)}

    async def _user_loop(self):
        while True:
            try:
                await connect_user(self.client, self.startup)
            except TelegramSessionError as error:
                self.client.connection_status = {"state": "login_required", "message": str(error)}
            except Exception as error:
                self.client.connection_status = {"state": "error", "message": f"Telegram 连接失败（{type(error).__name__}），正在重试"}
                logger.warning("Telegram connection failed: %s", type(error).__name__)
            await asyncio.sleep(15)

    async def _bot_loop(self):
        while True:
            try:
                await self.bot.start()
                self.bot_status = {"state": "ready", "message": "Bot 已连接"}
                await self.bot.run_forever()
            except Exception as error:
                self.bot_status = {"state": "error", "message": f"Bot 连接失败（{type(error).__name__}），检查 .env 中的配置"}
                logger.warning("Bot connection failed: %s", type(error).__name__)
            finally:
                await self.bot.stop()
            if self.bot_status["state"] == "ready":
                self.bot_status = {"state": "connecting", "message": "Bot 连接已断开，正在重试"}
            await asyncio.sleep(15)

    async def run(self):
        """Run the engine without HTTP, useful for runtime lifecycle checks."""
        try:
            await self.start_background()
            await asyncio.Event().wait()
        finally:
            await self.shutdown()
