"""Telegram Bot for managing forwarding tasks."""
import logging
from typing import Optional
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.custom import Button

from tg_forwarder.tasks.manager import TaskManager
from .wizard import TaskWizardMixin


logger = logging.getLogger(__name__)


class ForwarderBot(TaskWizardMixin):
    """Telegram Bot for managing forwarding tasks via commands and buttons."""

    def __init__(self, startup, task_manager: TaskManager):
        self.startup = startup
        self.bot_token = startup.bot_token
        self.admin_ids = startup.admin_ids
        self.config_manager = task_manager.config_manager
        self.progress_tracker = task_manager.progress_tracker
        self._task_manager = task_manager
        self._bot: Optional[TelegramClient] = None
        self._pending_tasks = {}  # user_id -> task being created

    async def start(self) -> None:
        """Start the bot."""
        self._bot = TelegramClient(StringSession(), self.startup.api_id,
            self.startup.api_hash, proxy=self.startup.proxy)
        await self._bot.start(bot_token=self.bot_token)
        self._register_handlers()
        logger.info("Bot started")

    def _register_handlers(self) -> None:
        """Register message and callback handlers."""

        @self._bot.on(events.NewMessage(pattern="/start$"))
        async def start_handler(event):
            if not self._is_admin(event.sender_id):
                return
            buttons = [
                [Button.inline("📋 任务列表", b"list")],
                [Button.inline("➕ 添加任务", b"add")],
                [Button.inline("📊 运行状态", b"status")],
                [Button.inline("🔄 重载配置", b"reload")],
            ]
            await event.respond(
                "🤖 **Telegram Forwarder Bot**\n\n"
                "点击下方按钮进行操作：",
                buttons=buttons
            )

        @self._bot.on(events.NewMessage(pattern="/list"))
        async def list_handler(event):
            if not self._is_admin(event.sender_id):
                return
            await self._handle_list(event)

        @self._bot.on(events.NewMessage(pattern="/add"))
        async def add_handler(event):
            if not self._is_admin(event.sender_id):
                return
            await self._handle_add_start(event)

        @self._bot.on(events.NewMessage(pattern="/status"))
        async def status_handler(event):
            if not self._is_admin(event.sender_id):
                return
            await self._handle_status(event)

        @self._bot.on(events.NewMessage(pattern="/cancel"))
        async def cancel_handler(event):
            if not self._is_admin(event.sender_id):
                return
            if event.sender_id in self._pending_tasks:
                del self._pending_tasks[event.sender_id]
                await event.respond("❌ 已取消添加任务")

        # Callback query handler for buttons
        @self._bot.on(events.CallbackQuery())
        async def callback_handler(event):
            if not self._is_admin(event.sender_id):
                return
            await self._handle_callback(event)

        @self._bot.on(events.NewMessage())
        async def message_handler(event):
            if not self._is_admin(event.sender_id):
                return
            if event.text and event.text.startswith("/"):
                return  # Skip commands
            if event.fwd_from:
                return  # Skip forwarded messages
            if event.sender_id in self._pending_tasks:
                await self._handle_add_step(event)

    def _is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    async def _handle_callback(self, event) -> None:
        """Handle button callbacks."""
        data = event.data.decode()

        if data == "list":
            await self._handle_list(event)
        elif data == "add":
            await self._handle_add_start(event)
        elif data == "status":
            await self._handle_status(event)
        elif data == "reload":
            await self._handle_reload(event)
        elif data == "main_menu":
            buttons = [
                [Button.inline("📋 任务列表", b"list")],
                [Button.inline("➕ 添加任务", b"add")],
                [Button.inline("📊 运行状态", b"status")],
                [Button.inline("🔄 重载配置", b"reload")],
            ]
            await event.edit("🤖 **Telegram Forwarder Bot**\n\n点击下方按钮进行操作：", buttons=buttons)
        elif data.startswith("task_"):
            # Show task actions
            task_id = data[5:]
            await self._show_task_actions(event, task_id)
        elif data.startswith("start_"):
            task_id = data[6:]
            await self._do_start_task(event, task_id)
        elif data.startswith("pause_"):
            task_id = data[6:]
            await self._do_pause(event, task_id)
        elif data.startswith("resume_"):
            task_id = data[7:]
            await self._do_resume(event, task_id)
        elif data.startswith("stop_"):
            task_id = data[5:]
            await self._do_stop(event, task_id)
        elif data.startswith("delete_"):
            task_id = data[7:]
            await self._do_delete(event, task_id)
        elif data.startswith("confirm_del_"):
            task_id = data[12:]
            await self._do_confirm_delete(event, task_id)

        await event.answer()

    async def _handle_list(self, event) -> None:
        """Handle list command - show tasks with buttons."""
        tasks = self._task_manager.list_tasks()

        if not tasks:
            buttons = [[Button.inline("➕ 添加任务", b"add")], [Button.inline("🔙 返回", b"main_menu")]]
            await event.respond("📋 没有配置任何任务", buttons=buttons)
            return

        msg = "📋 **任务列表**\n\n点击任务进行操作：\n\n"
        buttons = []

        for ts in tasks:
            status_emoji = {"running": "🟢", "paused": "🟡", "stopped": "🔴", "completed": "✅"}.get(ts.status, "⚪")

            count = ts.progress.forwarded_count if ts.progress else 0
            note = ts.config.note if ts.config and ts.config.note else ""

            # Show note in button if available, otherwise show task_id
            if note:
                btn_text = f"{status_emoji} {note[:15]} | {count}条"
            else:
                btn_text = f"{status_emoji} {ts.task_id[:12]} | {count}条"
            buttons.append([Button.inline(btn_text, f"task_{ts.task_id}".encode())])

        buttons.append([Button.inline("➕ 添加任务", b"add")])
        buttons.append([Button.inline("🔙 返回", b"main_menu")])

        try:
            await event.edit(msg, buttons=buttons)
        except:
            await event.respond(msg, buttons=buttons)

    async def _show_task_actions(self, event, task_id: str) -> None:
        """Show action buttons for a specific task."""
        ts = self._task_manager.get_task_status(task_id)

        status_emoji = {"running": "🟢", "paused": "🟡", "stopped": "🔴", "completed": "✅"}.get(ts.status, "⚪")

        msg = f"📌 **任务详情**\n\n"
        msg += f"ID: `{ts.task_id}`\n"
        if ts.config and ts.config.note:
            msg += f"备注: {ts.config.note}\n"
        msg += f"状态: {status_emoji} {ts.status}\n"
        if ts.config:
            msg += f"源: `{ts.config.source_channel}`\n"
            msg += f"目标: `{ts.config.target_channel}`\n"
            if ts.config.target_topic_id:
                msg += f"话题ID: {ts.config.target_topic_id}\n"
            msg += f"延迟: {ts.config.min_delay}s - {ts.config.max_delay}s\n"
            if ts.config.caption_prefix:
                msg += f"前缀: {ts.config.caption_prefix}\n"
            if ts.config.filter_keywords:
                msg += f"过滤词: {' '.join(ts.config.filter_keywords)}\n"
            if ts.config.required_hashtags:
                msg += f"必须包含: {' '.join(ts.config.required_hashtags)}\n"
                msg += f"删除Hashtag: {'是' if ts.config.remove_hashtags else '否'}\n"
            msg += f"以频道身份发送: {'是' if ts.config.send_as_channel else '否'}\n"
            msg += f"去重: {'是' if ts.config.deduplicate else '否'}\n"
        if ts.progress:
            msg += f"已转发: {ts.progress.forwarded_count} 条\n"

        # Build action buttons based on status
        buttons = []
        if ts.status == "stopped" or ts.status not in ["running", "paused"]:
            buttons.append([Button.inline("▶️ 启动", f"start_{task_id}".encode())])
        elif ts.status == "running":
            buttons.append([Button.inline("⏸️ 暂停", f"pause_{task_id}".encode())])
            buttons.append([Button.inline("⏹️ 停止", f"stop_{task_id}".encode())])
        elif ts.status == "paused":
            buttons.append([Button.inline("▶️ 恢复", f"resume_{task_id}".encode())])
            buttons.append([Button.inline("⏹️ 停止", f"stop_{task_id}".encode())])

        buttons.append([Button.inline("🗑️ 删除", f"delete_{task_id}".encode())])
        buttons.append([Button.inline("🔙 返回列表", b"list")])

        await event.edit(msg, buttons=buttons)

    async def _do_start_task(self, event, task_id: str) -> None:
        """Start a task."""
        try:
            await self._task_manager.start_task(task_id)
            await event.answer(f"✅ 任务已启动", alert=True)
            await self._show_task_actions(event, task_id)
        except Exception as e:
            await event.answer(f"❌ 启动失败: {e}", alert=True)

    async def _do_pause(self, event, task_id: str) -> None:
        """Pause a task."""
        try:
            await self._task_manager.pause_task(task_id)
            await event.answer(f"⏸️ 任务已暂停", alert=True)
            await self._show_task_actions(event, task_id)
        except Exception as e:
            await event.answer(f"❌ 暂停失败: {e}", alert=True)

    async def _do_resume(self, event, task_id: str) -> None:
        """Resume a task."""
        try:
            await self._task_manager.resume_task(task_id)
            await event.answer(f"▶️ 任务已恢复", alert=True)
            await self._show_task_actions(event, task_id)
        except Exception as e:
            await event.answer(f"❌ 恢复失败: {e}", alert=True)

    async def _do_stop(self, event, task_id: str) -> None:
        """Stop a task."""
        try:
            await self._task_manager.stop_task(task_id)
            await event.answer(f"⏹️ 任务已停止", alert=True)
            await self._show_task_actions(event, task_id)
        except Exception as e:
            await event.answer(f"❌ 停止失败: {e}", alert=True)

    async def _do_delete(self, event, task_id: str) -> None:
        """Show delete confirmation."""
        buttons = [
            [Button.inline("⚠️ 确认删除", f"confirm_del_{task_id}".encode())],
            [Button.inline("🔙 取消", f"task_{task_id}".encode())],
        ]
        await event.edit(f"⚠️ 确定要删除任务 `{task_id}` 吗？\n\n这将同时删除进度记录。", buttons=buttons)

    async def _do_confirm_delete(self, event, task_id: str) -> None:
        """Confirm and delete task."""
        try:
            await self._task_manager.delete_task(task_id, delete_progress=True)
            await event.answer(f"🗑️ 任务已删除", alert=True)
            await self._handle_list(event)
        except Exception as e:
            await event.answer(f"❌ 删除失败: {e}", alert=True)

    async def _handle_status(self, event) -> None:
        """Handle status command."""
        tasks = self._task_manager.list_tasks()

        running = sum(1 for t in tasks if t.status == "running")
        paused = sum(1 for t in tasks if t.status == "paused")
        stopped = sum(1 for t in tasks if t.status == "stopped")
        total_forwarded = sum(t.progress.forwarded_count for t in tasks if t.progress)

        msg = (
            "📊 **运行状态**\n\n"
            f"🟢 运行中: {running}\n"
            f"🟡 已暂停: {paused}\n"
            f"🔴 已停止: {stopped}\n"
            f"📨 总转发: {total_forwarded} 条"
        )
        buttons = [[Button.inline("🔙 返回", b"main_menu")]]
        try:
            await event.edit(msg, buttons=buttons)
        except:
            await event.respond(msg, buttons=buttons)

    async def _handle_reload(self, event) -> None:
        """Handle reload config command."""
        try:
            await self._task_manager.reload_runtime()
            task_count = len(self._task_manager.list_tasks())

            msg = (
                "🔄 **配置已重载**\n\n"
                f"✅ 成功从 SQLite 重新加载配置\n"
                f"✅ 成功从 SQLite 重新加载进度\n"
                f"📋 当前任务数: {task_count}\n\n"
                "⚠️ 注意：正在运行的任务不会自动更新，\n"
                "需要停止后重新启动才能应用新配置"
            )
            buttons = [[Button.inline("🔙 返回", b"main_menu")]]
            try:
                await event.edit(msg, buttons=buttons)
            except:
                await event.respond(msg, buttons=buttons)

            logger.info("Config and progress reloaded via bot command")
        except Exception as e:
            await event.answer(f"❌ 重载失败: {e}", alert=True)

    async def run_forever(self) -> None:
        await self._bot.run_until_disconnected()

    async def stop(self) -> None:
        if self._bot:
            await self._bot.disconnect()
