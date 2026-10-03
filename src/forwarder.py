"""Forwarder engine for Telegram Forwarder."""
import logging
import asyncio
from typing import Optional, List, Dict
from telethon.tl.types import Message
from telethon.errors import FloodWaitError

from .telegram_client import TelegramClientWrapper
from .message_handler import MessageHandler
from .progress_tracker import ProgressTracker
from .models import ForwardTask
from .utils import get_random_delay


logger = logging.getLogger(__name__)


class Forwarder:
    """Core forwarding engine that coordinates message forwarding."""

    def __init__(self, client: TelegramClientWrapper,
                 message_handler: MessageHandler,
                 progress_tracker: ProgressTracker,
                 group_semaphore: asyncio.Semaphore = None):
        self.client = client
        self.message_handler = message_handler
        self.progress_tracker = progress_tracker
        self._group_semaphore = group_semaphore or asyncio.Semaphore(1)
        self._running = False
        self._paused = False

    def _message_topic_id(self, message: Message) -> Optional[int]:
        reply_to = getattr(message, "reply_to", None)
        topic_id = getattr(reply_to, "reply_to_top_id", None)
        if topic_id is None:
            topic_id = getattr(reply_to, "reply_to_msg_id", None)
        if topic_id is None:
            topic_id = getattr(message, "reply_to_top_id", None)
        return int(topic_id) if topic_id is not None else None

    def _matches_source_topic(self, message: Message, source_topic_id: int) -> bool:
        return int(getattr(message, "id", -1)) == int(source_topic_id) or self._message_topic_id(message) == int(source_topic_id)

    def _filter_source_topic(self, messages: List[Message], source_topic_id: Optional[int]) -> List[Message]:
        if source_topic_id is None:
            return messages
        return [message for message in messages if self._matches_source_topic(message, source_topic_id)]

    def _group_messages(self, messages: List[Message]) -> List[List[Message]]:
        """
        Group messages by grouped_id (media albums) while preserving
        chronological order.

        Messages without grouped_id are treated as single-item groups. The
        resulting groups are ordered by the smallest message id inside each
        group, which keeps singles and albums in the same order they were
        fetched in.
        """
        ordered = sorted(messages, key=lambda m: m.id)
        result: List[List[Message]] = []
        groups: Dict[int, List[Message]] = {}
        
        for msg in ordered:
            grouped_id = getattr(msg, 'grouped_id', None)
            if grouped_id:
                if grouped_id not in groups:
                    groups[grouped_id] = [msg]
                    result.append(groups[grouped_id])
                else:
                    groups[grouped_id].append(msg)
            else:
                result.append([msg])
        
        return result

    async def run_task(self, task: ForwardTask) -> None:
        """
        Run a forwarding task.
        
        Fetches messages from source channel and forwards them to target,
        respecting the configured delay range.
        """
        self._running = True
        self._paused = False
        
        logger.info(f"Starting task {task.task_id}: {task.source_channel} -> {task.target_channel}")
        
        # Get last progress
        last_message_id = self.progress_tracker.get_last_message_id(task.task_id)
        logger.info(f"Resuming from message ID: {last_message_id}")
        
        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue
            
            try:
                # Fetch messages after last forwarded
                logger.debug(f"Fetching messages from {task.source_channel}, min_id={last_message_id}")
                messages = await self.client.get_messages(
                    task.source_channel,
                    min_id=last_message_id,
                    limit=50
                )
                logger.info(f"Fetched {len(messages) if messages else 0} messages")
                
                if not messages:
                    logger.info(f"No new messages for task {task.task_id}, waiting 30s...")
                    await asyncio.sleep(30)  # Wait before checking again
                    continue
                
                # Group messages by media album (preserving order)
                message_groups = self._group_messages(messages)
                logger.info(f"Grouped into {len(message_groups)} groups")
                batch_failed = False
                
                for original_group in message_groups:
                    if not self._running:
                        break

                    group = self._filter_source_topic(original_group, task.source_topic_id)
                    original_max_id = max(m.id for m in original_group)
                    if not group:
                        self.progress_tracker.advance_progress(task.task_id, original_max_id)
                        last_message_id = max(last_message_id, original_max_id)
                        continue

                    while self._paused:
                        await asyncio.sleep(1)
                    
                    # Process one group at a time across all tasks so a small
                    # machine never downloads multiple large media groups.
                    self.progress_tracker.begin_transfer(
                        task.task_id,
                        [m.id for m in group if getattr(m, "id", None) is not None],
                        len([m for m in group if self.message_handler.is_media_message(m)])
                    )
                    async with self._group_semaphore:
                        result = await self.process_message_group(group, task)
                    
                    # On failure, stop this batch and retry from the same
                    # position. Do NOT advance last_message_id, otherwise the
                    # failed message would be skipped forever.
                    if result == "failed":
                        self.progress_tracker.mark_transfer_state(task.task_id, "interrupted")
                        logger.warning(
                            f"[{task.task_id}] Failed to forward group "
                            f"{[m.id for m in group]}, will retry from "
                            f"message {last_message_id}"
                        )
                        batch_failed = True
                        break
                    
                    if result != "failed":
                        # The durable checkpoint is advanced below only after
                        # the whole group has completed or was explicitly skipped.
                        self.progress_tracker.clear_transfer(task.task_id)

                    # Advance to the highest message ID in the group. Groups
                    # are now processed in chronological order, but keep the
                    # max() guard to make progress never go backwards.
                    max_id = max(m.id for m in group)
                    last_message_id = max(last_message_id, max_id)
                    
                    # Only delay if we actually forwarded media
                    if result == "forwarded":
                        delay = get_random_delay(task.min_delay, task.max_delay)
                        logger.debug(f"Waiting {delay:.1f}s before next message")
                        await asyncio.sleep(delay)
                    # No delay for skipped messages
                
                if batch_failed:
                    logger.info(f"Retrying failed message for task {task.task_id} in 10s")
                    await asyncio.sleep(10)
                    
            except FloodWaitError as e:
                wait = getattr(e, 'seconds', 10) + 1
                logger.warning(
                    f"Task {task.task_id} hit FloodWait "
                    f"{getattr(e, 'seconds', '?')}s, waiting {wait}s"
                )
                await asyncio.sleep(wait)
            except Exception as e:
                logger.error(f"Error in task {task.task_id}: {e}")
                await asyncio.sleep(10)  # Wait before retry
        
        logger.info(f"Task {task.task_id} stopped")

    async def process_message_group(self, messages: List[Message], task: ForwardTask) -> str:
        """
        Process and forward a message group (single message or album).
        
        Returns:
            "forwarded" if media was forwarded
            "skipped" if no media to forward
            "filtered" if filtered by keywords
            "no_hashtag" if missing required hashtags
            "duplicate" if the media was already sent before
            "failed" if forwarding failed (progress is NOT advanced)
        """
        try:
            # Forward the group with task_id for progress tracking
            result = await self.message_handler.forward_message_group(
                messages, task.source_channel, task.target_channel,
                caption_prefix=task.caption_prefix,
                task_id=task.task_id,
                filter_keywords=task.filter_keywords,
                required_hashtags=task.required_hashtags,
                source_topic_id=task.source_topic_id,
                target_topic_id=task.target_topic_id,
                remove_hashtags=task.remove_hashtags,
                send_as_channel=task.send_as_channel,
                deduplicate=task.deduplicate
            )
            
            max_id = max(m.id for m in messages)
            
            if result.method == "skip":
                # No media, only advance the resume position
                self.progress_tracker.advance_progress(task.task_id, max_id)
                logger.debug(f"[{task.task_id}] Skipped non-media message(s)")
                return "skipped"
            
            if result.method == "filtered":
                # Filtered by keywords, only advance the resume position
                self.progress_tracker.advance_progress(task.task_id, max_id)
                logger.debug(f"[{task.task_id}] Filtered message(s) by keywords")
                return "filtered"
            
            if result.method == "no_hashtag":
                # Missing required hashtags, only advance the resume position
                self.progress_tracker.advance_progress(task.task_id, max_id)
                logger.debug(f"[{task.task_id}] Skipped message(s) - missing required hashtags")
                return "no_hashtag"
            
            if result.method == "duplicate":
                # Duplicate media, only advance the resume position
                self.progress_tracker.advance_progress(task.task_id, max_id)
                msg_ids = [m.id for m in messages]
                logger.info(f"[{task.task_id}] Skipped duplicate media, message IDs: {msg_ids}")
                return "duplicate"
            
            if result.success:
                count = result.forwarded_count or len(messages)
                self.progress_tracker.record_forwarded(task.task_id, max_id, count)
                self.progress_tracker.resolve_task_errors(task.task_id)
                progress = self.progress_tracker.get_task_progress(task.task_id)
                msg_ids = [m.id for m in messages]
                logger.info(
                    f"[{task.task_id}] Forwarded {len(messages)} message(s) {msg_ids} "
                    f"via {result.method} (total: {progress.forwarded_count})"
                )
                return "forwarded"
            else:
                logger.warning(
                    f"[{task.task_id}] Failed to forward messages: {result.error}. "
                    f"Will retry from the same message ID."
                )
                return "failed"
        except FloodWaitError as e:
            wait = getattr(e, 'seconds', 10) + 1
            logger.warning(
                f"[{task.task_id}] FloodWait {getattr(e, 'seconds', '?')}s, "
                f"waiting {wait}s before retry"
            )
            await asyncio.sleep(wait)
            return "failed"
        except Exception as e:
            max_id = max(m.id for m in messages)
            logger.error(
                f"[{task.task_id}] Error processing messages {max_id}: {e}. "
                f"Will retry."
            )
            return "failed"

    def stop(self) -> None:
        """Stop the forwarder."""
        self._running = False

    def pause(self) -> None:
        """Pause the forwarder."""
        self._paused = True

    def resume(self) -> None:
        """Resume the forwarder."""
        self._paused = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused


def calculate_resume_position(last_message_id: int) -> int:
    """
    Calculate the min_id for resuming from a given last message ID.
    
    The min_id parameter in Telegram API is exclusive, so we use
    the last_message_id directly to get messages after it.
    """
    return last_message_id
