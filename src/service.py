"""Web, Bot and forwarding share one task manager and one Telegram session."""
import asyncio
import logging

from .bot import ForwarderBot
from .task_manager import TaskManager
from .telegram_client import TelegramClientWrapper, TelegramSessionError
from .web_server import WebServer

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
        self.web = WebServer(progress_tracker, self.task_manager,
            host=startup.web_host, port=startup.web_port,
            web_password=config_manager.get_config().web_password,
            startup=startup, service_status=self.status)
        self._workers = []

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
        try:
            await self.web.start()
            self._workers = [asyncio.create_task(self._user_loop())]
            if self.bot:
                self._workers.append(asyncio.create_task(self._bot_loop()))
            logger.info("Management UI: http://%s:%s", self.startup.web_host, self.startup.web_port)
            await asyncio.Event().wait()
        finally:
            self.client.connection_status = {"state": "stopping", "message": "服务正在停止"}
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
            await self.web.stop()
            await self.task_manager.stop_all_tasks()
            if self.bot:
                await self.bot.stop()
            await self.client.disconnect()
