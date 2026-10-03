"""Ordered forwarding with durable receipts and album-aware fetching."""
import asyncio
import logging
from typing import List
from telethon.errors import FloodWaitError

from .models import ForwardTask
from .utils import get_random_delay

logger = logging.getLogger(__name__)


class Forwarder:
    def __init__(self, client, message_handler, progress_tracker, group_semaphore=None):
        self.client = client
        self.message_handler = message_handler
        self.progress_tracker = progress_tracker
        self._group_semaphore = group_semaphore if group_semaphore is not None else asyncio.Semaphore(1)
        self._running = False
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._ordered_ids = None
        self.error = ""
        self.album_settle_seconds = 2.0

    @staticmethod
    def _message_topic_id(message):
        reply = getattr(message, "reply_to", None)
        value = getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", None) or getattr(message, "reply_to_top_id", None)
        return int(value) if value is not None else None

    def _filter_source_topic(self, messages, source_topic_id):
        if source_topic_id is None:
            return messages
        return [m for m in messages if m.id == source_topic_id or self._message_topic_id(m) == source_topic_id]

    def _group_messages(self, messages):
        result, albums = [], {}
        for message in sorted(messages, key=lambda m: m.id):
            grouped_id = getattr(message, "grouped_id", None)
            if grouped_id:
                if grouped_id not in albums:
                    albums[grouped_id] = []
                    result.append(albums[grouped_id])
                albums[grouped_id].append(message)
            else:
                result.append([message])
        return result

    async def _fetch_batch(self, task, checkpoint):
        messages = list(await self.client.get_messages(task.source_channel, min_id=checkpoint, limit=50))
        if not messages:
            return []
        messages.sort(key=lambda m: m.id)
        tail = getattr(messages[-1], "grouped_id", None)
        if not tail:
            return messages
        # A batch may finish in the middle of an album. Scan until we observe
        # a later group, or the live edge stays unchanged for a settling window.
        empty_checks = 0
        while self._running:
            extra = list(await self.client.get_messages(task.source_channel, min_id=messages[-1].id, limit=50))
            extra.sort(key=lambda m: m.id)
            members = [m for m in extra if getattr(m, "grouped_id", None) == tail]
            if members:
                last_member = max(m.id for m in members)
                messages.extend(m for m in extra if m.id <= last_member)
                empty_checks = 0
            if any(getattr(m, "grouped_id", None) != tail and (not members or m.id > last_member) for m in extra):
                break
            if not extra:
                empty_checks += 1
                if empty_checks >= 2:
                    break
                await asyncio.sleep(self.album_settle_seconds)
        return messages

    async def _wait_ready(self):
        await self._resume_event.wait()
        return self._running

    async def run_task(self, task: ForwardTask):
        self._running = True
        self.error = ""
        failures = 0
        try:
            while self._running:
                if not await self._wait_ready():
                    break
                checkpoint = self.progress_tracker.get_last_message_id(task.task_id)
                try:
                    messages = await self._fetch_batch(task, checkpoint)
                    if not messages:
                        await asyncio.sleep(30)
                        continue
                    self._ordered_ids = [m.id for m in messages]
                    failed = False
                    for original_group in self._group_messages(messages):
                        if not await self._wait_ready():
                            break
                        done = self.progress_tracker.completed_ids(task.task_id)
                        if all(m.id in done or m.id <= self.progress_tracker.get_last_message_id(task.task_id) for m in original_group):
                            self.progress_tracker.complete_group(task.task_id, [m.id for m in original_group], "receipt", ordered_ids=self._ordered_ids)
                            continue
                        group = self._filter_source_topic(original_group, task.source_topic_id)
                        if not group:
                            self.progress_tracker.complete_group(task.task_id, [m.id for m in original_group], "topic", ordered_ids=self._ordered_ids)
                            continue
                        async with self._group_semaphore:
                            # Never start a new send after pausing while queued.
                            if self._paused:
                                # Re-fetch from the safe checkpoint after resume,
                                # preserving order instead of moving to the next group.
                                break
                            if not self._running:
                                break
                            self.progress_tracker.begin_transfer(task.task_id, [m.id for m in group], sum(self.message_handler.is_media_message(m) for m in group))
                            self.progress_tracker.update_transfer(task.task_id, {"ordered_ids": self._ordered_ids})
                            result = await self.process_message_group(group, task, original_group)
                        if result == "failed":
                            self.progress_tracker.mark_transfer_state(task.task_id, "interrupted")
                            failed = True
                            break
                        self.progress_tracker.clear_transfer(task.task_id)
                        failures = 0
                        if result == "forwarded":
                            await asyncio.sleep(get_random_delay(task.min_delay, task.max_delay))
                    if failed:
                        failures += 1
                        await asyncio.sleep(min(60, 2 ** min(failures, 5)))
                except FloodWaitError as error:
                    await asyncio.sleep(error.seconds + 1)
                except Exception as error:
                    from .errors import is_permanent_error
                    if is_permanent_error(error):
                        self.error = str(error)
                        self.progress_tracker.record_error(task.task_id, "transfer", error)
                        break
                    logger.exception("Task %s failed", task.task_id)
                    await asyncio.sleep(10)
        finally:
            self._running = False

    async def process_message_group(self, messages, task, original_group=None):
        try:
            result = await self.message_handler.forward_message_group(
                messages, task.source_channel, task.target_channel,
                caption_prefix=task.caption_prefix, task_id=task.task_id,
                filter_keywords=task.filter_keywords, required_hashtags=task.required_hashtags,
                source_topic_id=task.source_topic_id, target_topic_id=task.target_topic_id,
                remove_hashtags=task.remove_hashtags, send_as_channel=task.send_as_channel,
                deduplicate=task.deduplicate, hide_source=task.hide_source,
            )
            if not result.success:
                return "failed"
            outcome = result.method if result.method in {"skip", "filtered", "no_hashtag", "duplicate"} else "forwarded"
            ids = [m.id for m in (original_group or messages)]
            self.progress_tracker.complete_group(task.task_id, ids, outcome, result.forwarded_count if outcome == "forwarded" else 0, self._ordered_ids)
            if outcome == "forwarded":
                self.progress_tracker.resolve_task_errors(task.task_id)
                logger.info("[%s] Forwarded %s via %s", task.task_id, ids, result.method)
            return outcome
        except FloodWaitError:
            raise
        except Exception as error:
            from .errors import is_permanent_error
            if is_permanent_error(error):
                raise
            self.progress_tracker.record_error(task.task_id, "transfer", error, message_id=messages[0].id)
            return "failed"

    def stop(self):
        self._running = False
        self._resume_event.set()

    def pause(self):
        self._paused = True
        self._resume_event.clear()

    def resume(self):
        self._paused = False
        self._resume_event.set()

    @property
    def is_running(self):
        return self._running

    @property
    def is_paused(self):
        return self._paused


def calculate_resume_position(last_message_id):
    return last_message_id
