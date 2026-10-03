"""Telegram Bot for managing forwarding tasks."""
import logging
import uuid
from typing import Optional
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.custom import Button

from .config_manager import ConfigManager
from .progress_tracker import ProgressTracker
from .task_manager import TaskManager
from .telegram_client import TelegramClientWrapper
from .models import ForwardTask
from .validators import validate_channel_id, validate_delay_range


logger = logging.getLogger(__name__)


class ForwarderBot:
    """Telegram Bot for managing forwarding tasks via commands and buttons."""

    def __init__(self, bot_token: str, admin_ids: list,
                 config_manager: ConfigManager,
                 progress_tracker: ProgressTracker,
                 user_client: TelegramClientWrapper):
        self.bot_token = bot_token
        self.admin_ids = admin_ids
        self.config_manager = config_manager
        self.progress_tracker = progress_tracker
        self.user_client = user_client
        
        self._bot: Optional[TelegramClient] = None
        self._task_manager: Optional[TaskManager] = None
        self._pending_tasks = {}  # user_id -> task being created

    async def start(self) -> None:
        """Start the bot."""
        config = self.config_manager.get_config()
        self._bot = TelegramClient(
            StringSession(),
            config.api_id,
            config.api_hash
        )
        
        await self._bot.start(bot_token=self.bot_token)
        
        self._task_manager = TaskManager(
            self.user_client,
            self.config_manager,
            self.progress_tracker,
            temp_dir=getattr(config, 'temp_dir', 'temp') or 'temp'
        )
        
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

    async def _handle_add_start(self, event) -> None:
        """Start adding a new task - auto generate ID."""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        self._pending_tasks[event.sender_id] = {"step": "source", "task_id": task_id}
        
        msg = (
            "➕ **添加新任务**\n\n"
            f"任务ID: `{task_id}`\n\n"
            "请输入**源频道/群组ID**：\n"
            "格式: `-100xxxxxxxxxx`\n"
            "可以转发频道的任意消息给 @userinfobot 获取ID\n\n"
            "发送 /cancel 取消"
        )
        try:
            await event.edit(msg)
        except:
            await event.respond(msg)

    async def _handle_add_step(self, event) -> None:
        """Handle task creation steps."""
        user_id = event.sender_id
        pending = self._pending_tasks.get(user_id)
        if not pending:
            return
        
        text = event.text.strip()
        step = pending["step"]
        
        if step == "source":
            try:
                source = int(text)
                valid, err = validate_channel_id(source)
                if not valid:
                    await event.respond(f"❌ 无效的频道ID: {err}\n请重新输入：")
                    return
                pending["source"] = source
                pending["step"] = "target"
                await event.respond("请输入**目标频道/群组ID**（负数）：")
            except ValueError:
                await event.respond("❌ 请输入有效的数字ID")
        
        elif step == "target":
            try:
                target = int(text)
                valid, err = validate_channel_id(target)
                if not valid:
                    await event.respond(f"❌ 无效的频道ID: {err}\n请重新输入：")
                    return
                pending["target"] = target
                pending["step"] = "topic"
                await event.respond(
                    "请输入**目标话题ID**（可选）：\n"
                    "用于论坛群组，转发到指定话题\n"
                    "例如: `123` (话题ID是正整数)\n\n"
                    "发送 `-` 跳过（发送到默认位置）"
                )
            except ValueError:
                await event.respond("❌ 请输入有效的数字ID")
        
        elif step == "topic":
            topic_id = None
            if text != "-" and text != "0":
                try:
                    topic_id = int(text)
                    if topic_id < 0:
                        await event.respond("❌ 话题ID必须是正整数，请重新输入：")
                        return
                except ValueError:
                    await event.respond("❌ 请输入有效的数字ID")
                    return
            pending["topic_id"] = topic_id
            pending["step"] = "delay"
            await event.respond(
                "请输入**延迟范围**（秒）：\n"
                "格式: `最小-最大`，如 `10-20`\n"
                "或单个数字如 `15`"
            )
        
        elif step == "delay":
            try:
                parts = text.replace(" ", "").split("-")
                min_delay = float(parts[0])
                max_delay = float(parts[1]) if len(parts) > 1 else min_delay
                
                valid, err = validate_delay_range(min_delay, max_delay)
                if not valid:
                    await event.respond(f"❌ 无效的延迟范围: {err}\n请重新输入：")
                    return
                
                pending["min_delay"] = min_delay
                pending["max_delay"] = max_delay
                pending["step"] = "note"
                await event.respond(
                    "请输入**任务备注**（可选）：\n"
                    "例如: `转发科技新闻`\n\n"
                    "发送 `-` 跳过"
                )
            except (ValueError, IndexError):
                await event.respond("❌ 格式错误，请输入如 `10-20` 的格式")
        
        elif step == "note":
            note = "" if text == "-" else text
            pending["note"] = note
            pending["step"] = "prefix"
            await event.respond(
                "请输入**转发前缀**（可选）：\n"
                "转发时会添加到原始描述文本前面\n"
                "例如: `【转载】` 或 `@频道名`\n\n"
                "发送 `-` 跳过"
            )
        
        elif step == "prefix":
            prefix = "" if text == "-" else text
            pending["prefix"] = prefix
            pending["step"] = "filter"
            await event.respond(
                "请输入**过滤关键词**（可选）：\n"
                "包含这些关键词的消息将被跳过\n"
                "多个关键词用空格分隔\n"
                "例如: `广告 推广 加群`\n\n"
                "发送 `-` 跳过"
            )
        
        elif step == "filter":
            filter_keywords = []
            if text != "-":
                filter_keywords = [kw.strip() for kw in text.split() if kw.strip()]
            pending["filter_keywords"] = filter_keywords
            pending["step"] = "required_hashtags"
            await event.respond(
                "请输入**必须包含的Hashtag**（可选）：\n"
                "只有包含这些hashtag的消息才会被转发\n"
                "多个hashtag用空格分隔\n"
                "例如: `#自拍 #原创` 或 `自拍 原创`\n\n"
                "发送 `-` 跳过（转发所有消息）"
            )
        
        elif step == "required_hashtags":
            required_hashtags = []
            if text != "-":
                required_hashtags = [tag.strip() for tag in text.split() if tag.strip()]
            pending["required_hashtags"] = required_hashtags
            
            # Only ask about removing hashtags if we have required_hashtags
            if required_hashtags:
                pending["step"] = "remove_hashtags"
                await event.respond(
                    "是否在转发后**删除这些Hashtag**？\n\n"
                    "发送 `1` 删除hashtag\n"
                    "发送其他任意内容保留hashtag"
                )
            else:
                pending["remove_hashtags"] = False
                pending["step"] = "send_as_channel"
                await event.respond(
                    "是否以**目标频道/群组身份**发送？\n"
                    "（需要登录账号是目标群组的管理员）\n\n"
                    "发送 `1` 以频道身份发送\n"
                    "发送其他任意内容以个人身份发送"
                )
        
        elif step == "remove_hashtags":
            remove_hashtags = (text == "1")
            pending["remove_hashtags"] = remove_hashtags
            pending["step"] = "send_as_channel"
            logger.debug(f"User {user_id} set remove_hashtags={remove_hashtags}, input was: {text}")
            await event.respond(
                "是否以**目标频道/群组身份**发送？\n"
                "（需要登录账号是目标群组的管理员）\n\n"
                "发送 `1` 以频道身份发送\n"
                "发送其他任意内容以个人身份发送"
            )
        
        elif step == "send_as_channel":
            send_as_channel = (text == "1")
            pending["send_as_channel"] = send_as_channel
            pending["step"] = "deduplicate"
            logger.debug(f"User {user_id} set send_as_channel={send_as_channel}, input was: {text}")
            await event.respond(
                "是否启用**去重功能**？\n"
                "（基于文件ID，已转发过的媒体不会重复发送）\n\n"
                "发送 `1` 启用去重\n"
                "发送其他任意内容不启用"
            )
        
        elif step == "deduplicate":
            deduplicate = (text == "1")
            pending["deduplicate"] = deduplicate
            pending["step"] = "start_id"
            logger.debug(f"User {user_id} set deduplicate={deduplicate}, input was: {text}")
            await event.respond(
                "请输入**起始消息ID**（可选）：\n"
                "从该消息ID之后开始转发\n"
                "例如: `12345`\n\n"
                "发送 `-` 或 `0` 从头开始"
            )
        
        elif step == "start_id":
            start_id = 0
            if text != "-" and text != "0":
                try:
                    start_id = int(text)
                    if start_id < 0:
                        await event.respond("❌ 消息ID必须是正整数，请重新输入：")
                        return
                except ValueError:
                    await event.respond("❌ 请输入有效的数字ID")
                    return
            
            task = ForwardTask(
                task_id=pending["task_id"],
                source_channel=pending["source"],
                target_channel=pending["target"],
                min_delay=pending["min_delay"],
                max_delay=pending["max_delay"],
                enabled=True,
                note=pending["note"],
                caption_prefix=pending["prefix"],
                filter_keywords=pending.get("filter_keywords", []),
                required_hashtags=pending.get("required_hashtags", []),
                target_topic_id=pending.get("topic_id"),
                remove_hashtags=pending.get("remove_hashtags", False),
                send_as_channel=pending.get("send_as_channel", False),
                deduplicate=pending.get("deduplicate", False)
            )
            
            self.config_manager.add_task(task)
            
            # Set start_id in progress if specified
            if start_id > 0:
                self.progress_tracker.advance_progress(task.task_id, start_id)
            
            del self._pending_tasks[user_id]
            
            buttons = [
                [Button.inline("▶️ 立即启动", f"start_{task.task_id}".encode())],
                [Button.inline("📋 查看列表", b"list")],
            ]
            note_text = f"备注: {task.note}\n" if task.note else ""
            topic_text = f"话题ID: {task.target_topic_id}\n" if task.target_topic_id else ""
            prefix_text = f"前缀: {task.caption_prefix}\n" if task.caption_prefix else ""
            filter_text = f"过滤词: {' '.join(task.filter_keywords)}\n" if task.filter_keywords else ""
            hashtag_text = f"必须包含: {' '.join(task.required_hashtags)}\n" if task.required_hashtags else ""
            remove_text = f"删除Hashtag: {'是' if task.remove_hashtags else '否'}\n" if task.required_hashtags else ""
            send_as_text = f"以频道身份发送: {'是' if task.send_as_channel else '否'}\n"
            dedup_text = f"去重: {'是' if task.deduplicate else '否'}\n"
            start_text = f"起始ID: {start_id}\n" if start_id > 0 else ""
            await event.respond(
                f"✅ **任务添加成功！**\n\n"
                f"ID: `{task.task_id}`\n"
                f"源: `{task.source_channel}`\n"
                f"目标: `{task.target_channel}`\n"
                f"{topic_text}"
                f"延迟: {task.min_delay}s - {task.max_delay}s\n"
                f"{note_text}"
                f"{prefix_text}"
                f"{filter_text}"
                f"{hashtag_text}"
                f"{remove_text}"
                f"{send_as_text}"
                f"{dedup_text}"
                f"{start_text}",
                buttons=buttons
            )

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
            # Reload config from file
            self.config_manager.reload()
            config = self.config_manager.get_config()
            task_count = len(config.tasks) if config else 0
            
            # Reload progress from file
            self.progress_tracker.load_progress()
            
            msg = (
                "🔄 **配置已重载**\n\n"
                f"✅ 成功从文件重新加载配置\n"
                f"✅ 成功从文件重新加载进度\n"
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
        if self._task_manager:
            await self._task_manager.stop_all_tasks()
        if self._bot:
            await self._bot.disconnect()
