"""Interactive Bot task creation conversation."""
import logging
import uuid
from telethon.tl.custom import Button
from tg_forwarder.tasks.models import ForwardTask
from tg_forwarder.tasks.validation import validate_channel_id, validate_delay_range

logger = logging.getLogger(__name__)


class TaskWizardMixin:
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
            pending["step"] = "require_video"
            logger.debug(f"User {user_id} set deduplicate={deduplicate}, input was: {text}")
            await event.respond(
                "是否**仅转发含视频的消息**？\n"
                "开启后跳过单张图片和纯图片组，含视频的混合媒体组整组转发\n\n"
                "发送 `1` 开启\n"
                "发送其他任意内容关闭"
            )

        elif step == "require_video":
            pending["require_video"] = (text == "1")
            pending["step"] = "include_topic_name"
            await event.respond(
                "是否在**标题携带来源话题名**？\n"
                "有话题时按「自定义前缀 话题名 原标题」发送，不添加括号\n\n"
                "发送 `1` 开启\n"
                "发送其他任意内容关闭"
            )

        elif step == "include_topic_name":
            pending["include_topic_name"] = (text == "1")
            pending["step"] = "start_id"
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
                deduplicate=pending.get("deduplicate", False),
                require_video=pending.get("require_video", False),
                include_topic_name=pending.get("include_topic_name", False)
            )

            try:
                self._task_manager.create_task(task, start_id=start_id)
            except ValueError as error:
                await event.respond(f"❌ 创建失败: {error}\n发送 /cancel 取消并重新创建")
                return

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
            video_text = "仅转发含视频的消息: 开启\n" if task.require_video else ""
            topic_name_text = "标题携带来源话题名: 开启\n" if task.include_topic_name else ""
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
                f"{video_text}"
                f"{topic_name_text}"
                f"{start_text}",
                buttons=buttons
            )
