"""Message handler for Telegram Forwarder."""
import asyncio
import logging
import os
import re
import shutil
import time
from functools import wraps
from pathlib import Path
from typing import Optional, List
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
from telethon.errors import FloodWaitError

from .telegram_client import TelegramClientWrapper
from .models import ForwardResult
from .dedup_tracker import DedupTracker
from .errors import is_permanent_error
from .workspace import WorkspaceStore, atomic_json
from .transfer import load_manifest
from .reliable_sender import encode_media, decode_media
from .database import Database
from telethon.errors import ChatForwardsRestrictedError, FileReferenceExpiredError, FilerefUpgradeNeededError

COPY_FALLBACK_ERRORS = (ChatForwardsRestrictedError, FileReferenceExpiredError, FilerefUpgradeNeededError)


logger = logging.getLogger(__name__)


def disk_guard(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        semaphore = getattr(self.client, "disk_semaphore", None)
        if semaphore is None:
            return await method(self, *args, **kwargs)
        async with semaphore:
            return await method(self, *args, **kwargs)
    return wrapped


class MessageHandler:
    """Handles message forwarding - only media (photos/videos/media groups)."""

    def __init__(self, client: TelegramClientWrapper, temp_dir: str = "temp",
                 dedup_tracker: DedupTracker = None,
                 min_free_disk_mb: int = 1024):
        self.client = client
        self.temp_dir = temp_dir
        self.dedup_tracker = dedup_tracker
        self.progress_tracker = getattr(client, "_progress_tracker", None)
        self.min_free_disk_mb = max(0, int(min_free_disk_mb))
        self.workspaces = WorkspaceStore(temp_dir)
        self._managed = False
        os.makedirs(temp_dir, exist_ok=True)

    def _cached_upload(self, message, target):
        if not self._managed:
            return None
        path = Path(self.temp_dir) / f"{message.id}.uploaded.json"
        data = load_manifest(path)
        media = getattr(message.media, "document", None) or getattr(message.media, "photo", None)
        if data.get("source_id") != getattr(media, "id", None) or data.get("target") != target or time.time() - data.get("created_at", 0) > 3600:
            path.unlink(missing_ok=True)
            return None
        try:
            return decode_media(data["media"])
        except (ValueError, KeyError, TypeError):
            path.unlink(missing_ok=True)
            return None

    def _save_uploaded(self, message, target, uploaded):
        if not self._managed:
            return
        media = getattr(message.media, "document", None) or getattr(message.media, "photo", None)
        atomic_json(Path(self.temp_dir) / f"{message.id}.uploaded.json", {
            "source_id": getattr(media, "id", None), "target": target,
            "created_at": time.time(), "media": encode_media(uploaded),
        })

    async def _wait_for_disk_space(self, message: Message = None, task_id: str = None) -> None:
        """Wait until local temp storage can hold one more media file."""
        if self.min_free_disk_mb <= 0:
            return

        required_bytes = 0
        document = getattr(getattr(message, "media", None), "document", None)
        if document:
            required_bytes = int(getattr(document, "size", 0) or 0)
        if self._managed and message is not None:
            existing = sum(p.stat().st_size for p in Path(self.temp_dir).glob(f"{message.id}_*")
                           if p.is_file() and not p.name.endswith((".json", ".tmp")))
            required_bytes = max(0, required_bytes - existing)

        minimum_free = self.min_free_disk_mb * 1024 * 1024
        while True:
            free_bytes = shutil.disk_usage(self.temp_dir).free
            if free_bytes >= minimum_free + required_bytes:
                return

            logger.warning(
                "[%s] Waiting for local disk space: %.1f MB free, "
                "need %.1f MB plus media size; retrying in 30s",
                task_id or "default",
                free_bytes / (1024 * 1024),
                self.min_free_disk_mb,
            )
            await asyncio.sleep(30)

    def is_media_message(self, message: Message) -> bool:
        """Check if message contains photo or video."""
        if not message.media:
            return False

        # Photo
        if isinstance(message.media, MessageMediaPhoto):
            return True

        # Video/Document
        if isinstance(message.media, MessageMediaDocument):
            if message.media.document:
                mime = getattr(message.media.document, 'mime_type', '')
                # Video or image
                if mime.startswith('video/') or mime.startswith('image/'):
                    return True

        return False

    def _apply_prefix(self, text: str, prefix: str) -> str:
        """Apply prefix to caption text."""
        if not prefix:
            return text
        if not text:
            return prefix
        return f"{prefix} {text}"

    @staticmethod
    def _hashtag_pattern(hashtag):
        tag = hashtag if hashtag.startswith("#") else "#" + hashtag
        return re.compile(r"(?<![\w#])" + re.escape(tag) + r"(?!\w)", re.IGNORECASE)

    def _remove_hashtags_from_text(self, text: str, hashtags: List[str]) -> str:
        if not text or not hashtags:
            return text
        result = text
        for hashtag in hashtags:
            result = self._hashtag_pattern(hashtag).sub("", result)
        return re.sub(r"[ \t]+", " ", result).strip()

    def _contains_filter_keywords(self, messages: List[Message], keywords: List[str]) -> bool:
        """Check if any message caption contains filter keywords."""
        if not keywords:
            return False

        for msg in messages:
            caption = msg.text or ""
            if not caption:
                continue
            caption_lower = caption.lower()
            for keyword in keywords:
                if keyword.lower() in caption_lower:
                    logger.debug(f"Message {msg.id} caption contains filter keyword: {keyword}")
                    return True
        return False

    def _contains_required_hashtags(self, messages: List[Message], required_hashtags: List[str]) -> bool:
        """
        Check if any message caption contains at least one of the required hashtags.
        Returns True if a required hashtag is found, False otherwise.
        """
        if not required_hashtags:
            return True  # No requirement, always pass

        for msg in messages:
            caption = msg.text or ""
            if not caption:
                continue
            caption_lower = caption.lower()
            for hashtag in required_hashtags:
                tag = hashtag.lower() if hashtag.startswith('#') else f"#{hashtag.lower()}"
                if self._hashtag_pattern(hashtag).search(caption_lower):
                    logger.debug(f"Message {msg.id} contains required hashtag: {hashtag}")
                    return True
        return False

    def _message_topic_id(self, message: Message) -> Optional[int]:
        """Return the forum topic root id carried by a Telegram message."""
        reply_to = getattr(message, "reply_to", None)
        topic_id = getattr(reply_to, "reply_to_top_id", None)
        if topic_id is None:
            topic_id = getattr(reply_to, "reply_to_msg_id", None)
        if topic_id is None:
            topic_id = getattr(message, "reply_to_top_id", None)
        return int(topic_id) if topic_id is not None else None

    def _filter_source_topic(self, messages: List[Message], source_topic_id: Optional[int]) -> List[Message]:
        if source_topic_id is None:
            return messages
        topic_id = int(source_topic_id)
        return [
            message for message in messages
            if int(getattr(message, "id", -1)) == topic_id
            or self._message_topic_id(message) == topic_id
        ]

    async def forward_message_group(self, messages, source_channel, target_channel, **kwargs):
        task_id = kwargs.get("task_id")
        if not task_id or not isinstance(getattr(self.progress_tracker, "db", None), Database):
            return await self._forward_message_group(messages, source_channel, target_channel, **kwargs)
        original = self.temp_dir
        path = self.workspaces.open(task_id, source_channel, [m.id for m in messages])
        self.temp_dir = str(path)
        self._managed = True
        try:
            result = await self._forward_message_group(messages, source_channel, target_channel, **kwargs)
            if result.success:
                self.workspaces.release(path)
                self.workspaces.cleanup(only_path=path)
            return result
        finally:
            self._managed = False
            self.temp_dir = original
            self.workspaces.release(path)

    async def _forward_message_group(self, messages: List[Message],
                                    source_channel: int,
                                    target_channel: int,
                                    caption_prefix: str = "",
                                    task_id: str = None,
                                    filter_keywords: List[str] = None,
                                    required_hashtags: List[str] = None,
                                    target_topic_id: int = None,
                                    remove_hashtags: bool = False,
                                    send_as_channel: bool = False,
                                    deduplicate: bool = False,
                                    source_topic_id: int = None,
                                    hide_source: bool = True) -> ForwardResult:
        """
        Forward a group of messages (single or album).
        Only forwards if there's media content.
        Skips if message contains filter keywords.
        Skips if message doesn't contain required hashtags (when specified).
        Skips if deduplicate is enabled and media was already sent.
        """
        messages = self._filter_source_topic(messages, source_topic_id)
        if not messages:
            logger.debug(f"Message group skipped - source topic mismatch")
            return ForwardResult(success=True, method="skip")

        # Check for filter keywords first (skip if contains)
        if filter_keywords and self._contains_filter_keywords(messages, filter_keywords):
            logger.debug(f"Message group filtered by keywords")
            return ForwardResult(success=True, method="filtered")

        # Check for required hashtags (skip if doesn't contain any)
        if required_hashtags and not self._contains_required_hashtags(messages, required_hashtags):
            logger.debug(f"Message group skipped - missing required hashtags")
            return ForwardResult(success=True, method="no_hashtag")

        # Filter to only media messages
        media_messages = [m for m in messages if self.is_media_message(m)]

        if not media_messages:
            logger.debug(f"No media in message group, skipping")
            return ForwardResult(success=True, method="skip")

        # Check for duplicates if enabled. If only part of a group is
        # duplicated, forward the remaining new media instead of dropping
        # the whole album.
        if deduplicate and self.dedup_tracker:
            unique_messages = [m for m in media_messages if not self.dedup_tracker.is_duplicate(m)]
            if not unique_messages:
                logger.debug(f"Message group skipped - duplicate media detected")
                return ForwardResult(success=True, method="duplicate")
            media_messages = unique_messages

        # Determine hashtags to remove (only if remove_hashtags is True and we have required_hashtags)
        hashtags_to_remove = required_hashtags if (remove_hashtags and required_hashtags) else None

        # Determine send_as entity (target channel if send_as_channel is True)
        send_as = target_channel if send_as_channel else None

        if not hide_source:
            await self.client.send_existing_media(target_channel, [self.client.input_media_with_cover(m) for m in media_messages],
                task_id=task_id, message_ids=[m.id for m in media_messages], source=source_channel, reply_to=target_topic_id)
            result = ForwardResult(True, "forward", forwarded_count=len(media_messages))
        # Single message
        elif len(media_messages) == 1:
            result = await self._forward_single(media_messages[0], target_channel, caption_prefix, task_id, target_topic_id, hashtags_to_remove, send_as)
        else:
            # Album (multiple media)
            result = await self._forward_album(media_messages, target_channel, caption_prefix, task_id, target_topic_id, hashtags_to_remove, send_as)

        # Record the number of media actually forwarded (after duplicate
        # filtering only the newly forwarded items are in media_messages).
        if result.success and result.method not in ["skip", "filtered", "no_hashtag", "duplicate"]:
            result.forwarded_count = len(media_messages)

        # Mark as sent if successful and dedup is enabled
        if result.success and deduplicate and self.dedup_tracker and result.method not in ["skip", "filtered", "no_hashtag", "duplicate"]:
            self.dedup_tracker.mark_group_as_sent(media_messages)

        return result

    async def _forward_single(self, message: Message, target_channel: int,
                              caption_prefix: str = "", task_id: str = None,
                              target_topic_id: int = None,
                              hashtags_to_remove: List[str] = None,
                              send_as: int = None) -> ForwardResult:
        """Forward a single media message."""
        # Try copy first (using bot if available)
        success = await self.copy_message(message, target_channel, caption_prefix, target_topic_id, hashtags_to_remove, send_as, task_id)
        if success:
            return ForwardResult(success=True, method="copy")

        # Fallback to download
        logger.info(f"Copy failed for message {message.id}, trying download")
        success = await self.download_and_send(message, target_channel, caption_prefix, task_id, target_topic_id, hashtags_to_remove, send_as)
        if success:
            return ForwardResult(success=True, method="download")

        return ForwardResult(success=False, method="copy", error="Failed to forward message")

    async def _forward_album(self, messages: List[Message], target_channel: int,
                             caption_prefix: str = "", task_id: str = None,
                             target_topic_id: int = None,
                             hashtags_to_remove: List[str] = None,
                             send_as: int = None) -> ForwardResult:
        """Forward an album (media group) as a single unit."""
        try:
            target_entity = await self.client.get_entity(target_channel)

            # Collect all media from the album
            media_list = [self.client.input_media_with_cover(m) for m in messages]

            # Use caption from first message that has one
            caption = None
            for m in messages:
                text = m.text or m.message
                if text:
                    caption = self._apply_prefix(text, caption_prefix)
                    break

            # If no original caption but has prefix, use prefix as caption
            if caption is None and caption_prefix:
                caption = caption_prefix

            # Remove hashtags if specified
            if caption and hashtags_to_remove:
                caption = self._remove_hashtags_from_text(caption, hashtags_to_remove)

            # Send as album (with reply_to for topic support)
            send_kwargs = {
                "caption": caption
            }
            if target_topic_id:
                send_kwargs["reply_to"] = target_topic_id
            if send_as:
                send_as_entity = await self.client.get_entity(send_as)
                send_kwargs["send_as"] = send_as_entity

            await self.client.send_existing_media(target_entity, media_list, task_id=task_id,
                message_ids=[m.id for m in messages], caption=caption, reply_to=target_topic_id, send_as=send_as)
            logger.info(f"Sent album with {len(media_list)} items" + (f" to topic {target_topic_id}" if target_topic_id else "") + (f" as channel" if send_as else ""))
            return ForwardResult(success=True, method="copy_album")
        except FloodWaitError:
            raise
        except Exception as e:
            if is_permanent_error(e):
                raise
            if not isinstance(e, COPY_FALLBACK_ERRORS):
                raise
            logger.warning(f"Album copy failed: {e}, trying individual download")
            return await self._download_and_send_album(messages, target_channel, caption_prefix, task_id, target_topic_id, hashtags_to_remove, send_as)

    @disk_guard
    async def _download_and_send_album(self, messages: List[Message], target_channel: int,
                                       caption_prefix: str = "", task_id: str = None,
                                       target_topic_id: int = None,
                                       hashtags_to_remove: List[str] = None,
                                       send_as: int = None) -> ForwardResult:
        """Download and upload album items one at a time before sending."""
        file_paths = []
        all_artwork_paths = []
        uploaded_media = []
        try:
            target_entity = await self.client.get_entity(target_channel)

            caption = None
            for m in messages:
                text = m.text or m.message
                if text:
                    caption = self._apply_prefix(text, caption_prefix)
                    break

            if caption is None and caption_prefix:
                caption = caption_prefix
            if caption and hashtags_to_remove:
                caption = self._remove_hashtags_from_text(caption, hashtags_to_remove)

            media_messages = [m for m in messages if self.is_media_message(m)]
            total_files = len(media_messages)
            if task_id:
                self.progress_tracker.begin_transfer(
                    task_id,
                    [m.id for m in media_messages],
                    total_files
                )

            # Keep only the current source file on disk. Telegram retains the
            # uploaded handle, which lets the final request remain one album.
            for index, msg in enumerate(media_messages, start=1):
                cached = self._cached_upload(msg, target_channel)
                if cached is not None:
                    uploaded_media.append(cached)
                    continue
                await self._wait_for_disk_space(msg, task_id)
                artwork = await self.client.prepare_media_artwork(msg, self.temp_dir, task_id)
                all_artwork_paths.extend(artwork.paths)
                msg = artwork.message
                path = await self.client.download_media(
                    msg,
                    self.temp_dir,
                    task_id=task_id,
                    file_index=index,
                    total_files=total_files,
                    clear_progress=False
                )
                if not path:
                    raise RuntimeError(f"Media {msg.id} could not be downloaded; album remains incomplete")
                file_paths.append(path)

                document = getattr(msg.media, 'document', None)
                attrs = document.attributes if document else None
                media = await self.client.upload_media_for_album(
                    path,
                    attributes=attrs,
                    thumb=artwork.thumb,
                    cover=artwork.cover,
                    entity=target_entity,
                    task_id=task_id,
                    file_index=index,
                    total_files=total_files,
                    cleanup_after_upload=True,
                    message_id=msg.id
                )
                uploaded_media.append(media)
                self._save_uploaded(msg, target_channel, media)
                if self._managed:
                    self._cleanup_file(path)
                    for artwork_path in artwork.paths:
                        self._cleanup_file(artwork_path)

            if not uploaded_media:
                return ForwardResult(success=False, method="download", error="No files downloaded")

            sent = await self.client.send_uploaded_album(
                target_entity,
                uploaded_media,
                caption=caption,
                task_id=task_id,
                reply_to=target_topic_id,
                send_as=send_as,
                message_ids=[m.id for m in media_messages]
            )
            if not sent:
                raise RuntimeError("Telegram did not confirm the album send")
            if task_id:
                self.progress_tracker.clear_transfer(task_id)

            logger.info(f"Downloaded and sent album with {len(uploaded_media)} items" + (f" to topic {target_topic_id}" if target_topic_id else "") + (f" as channel" if send_as else ""))
            return ForwardResult(success=True, method="download_album")
        except FloodWaitError:
            raise
        except Exception as e:
            if is_permanent_error(e):
                raise
            if self._managed and isinstance(e, (FileReferenceExpiredError, FilerefUpgradeNeededError)):
                for message in messages:
                    (Path(self.temp_dir) / f"{message.id}.uploaded.json").unlink(missing_ok=True)
            logger.error(f"Download album failed: {e}")
            return ForwardResult(success=False, method="download", error=str(e))
        finally:
            if not self._managed:
                for path in file_paths:
                    self._cleanup_file(path)
                for path in all_artwork_paths:
                    self._cleanup_file(path)

    async def forward_message(self, message: Message,
                             source_channel: int,
                             target_channel: int,
                             caption_prefix: str = "",
                             task_id: str = None,
                             filter_keywords: List[str] = None,
                             required_hashtags: List[str] = None,
                             target_topic_id: int = None,
                             remove_hashtags: bool = False,
                             send_as_channel: bool = False,
                             deduplicate: bool = False,
                             source_topic_id: int = None) -> ForwardResult:
        """
        Forward a message - only if it's media (photo/video).
        Skips text-only messages without delay.
        """
        return await self.forward_message_group(
            [message], source_channel, target_channel,
            caption_prefix=caption_prefix,
            task_id=task_id,
            filter_keywords=filter_keywords,
            required_hashtags=required_hashtags,
            source_topic_id=source_topic_id,
            target_topic_id=target_topic_id,
            remove_hashtags=remove_hashtags,
            send_as_channel=send_as_channel,
            deduplicate=deduplicate,
        )

    async def copy_message(self, message: Message, target_channel: int,
                          caption_prefix: str = "", target_topic_id: int = None,
                          hashtags_to_remove: List[str] = None,
                          send_as: int = None, task_id: str = None) -> bool:
        """Copy message to target without showing source."""
        try:
            target_entity = await self.client.get_entity(target_channel)
            text = message.text or message.message or ""
            caption = self._apply_prefix(text, caption_prefix) if text else caption_prefix

            if caption and hashtags_to_remove:
                caption = self._remove_hashtags_from_text(caption, hashtags_to_remove)

            send_kwargs = {
                "caption": caption if caption else None
            }
            if target_topic_id:
                send_kwargs["reply_to"] = target_topic_id
            if send_as:
                send_as_entity = await self.client.get_entity(send_as)
                send_kwargs["send_as"] = send_as_entity

            await self.client.send_existing_media(target_entity, self.client.input_media_with_cover(message),
                task_id=task_id, message_ids=[message.id], caption=caption, reply_to=target_topic_id, send_as=send_as)
            return True
        except FloodWaitError:
            raise
        except Exception as e:
            if is_permanent_error(e) or not isinstance(e, COPY_FALLBACK_ERRORS):
                raise
            logger.warning(f"Copy message {message.id} failed: {e}")
            return False

    @disk_guard
    async def download_and_send(self, message: Message, target_channel: int,
                               caption_prefix: str = "", task_id: str = None,
                               target_topic_id: int = None,
                               hashtags_to_remove: List[str] = None,
                               send_as: int = None) -> bool:
        """Fallback: Download and re-upload with metadata preserved."""
        file_path = None
        artwork = None
        try:
            text = message.text or message.message or ""
            caption = self._apply_prefix(text, caption_prefix) if text else caption_prefix

            if caption and hashtags_to_remove:
                caption = self._remove_hashtags_from_text(caption, hashtags_to_remove)

            cached = self._cached_upload(message, target_channel)
            if cached is not None:
                return await self.client.send_existing_media(target_channel, cached,
                    task_id=task_id, message_ids=[message.id], caption=caption, reply_to=target_topic_id, send_as=send_as)
            await self._wait_for_disk_space(message, task_id)
            artwork = await self.client.prepare_media_artwork(message, self.temp_dir, task_id)
            message = artwork.message
            file_path = await self.client.download_media(
                message, self.temp_dir, task_id=task_id, clear_progress=False
            )

            if file_path:
                document = getattr(message.media, 'document', None)
                attributes = document.attributes if document else None
                if self._managed:
                    entity = await self.client.get_entity(target_channel)
                    media = await self.client.upload_media_for_album(file_path, attributes=attributes,
                        thumb=artwork.thumb, cover=artwork.cover, task_id=task_id, message_id=message.id,
                        cleanup_after_upload=False, entity=entity)
                    self._save_uploaded(message, target_channel, media)
                    self._cleanup_file(file_path)
                    success = await self.client.send_existing_media(entity, media, task_id=task_id,
                        message_ids=[message.id], caption=caption, reply_to=target_topic_id, send_as=send_as)
                else:
                    success = await self.client.send_file_with_metadata(
                        target_channel, file_path, caption=caption if caption else None,
                        attributes=attributes, thumb=artwork.thumb, cover=artwork.cover,
                        task_id=task_id, reply_to=target_topic_id, send_as=send_as, message_id=message.id)
                if success and task_id and self.progress_tracker:
                    self.progress_tracker.clear_transfer(task_id)
                return success
            return False
        except FloodWaitError:
            raise
        except Exception as e:
            if is_permanent_error(e):
                raise
            if self._managed and isinstance(e, (FileReferenceExpiredError, FilerefUpgradeNeededError)):
                (Path(self.temp_dir) / f"{message.id}.uploaded.json").unlink(missing_ok=True)
            logger.error(f"Download and send failed: {e}")
            return False
        finally:
            if not self._managed:
                if file_path:
                    self._cleanup_file(file_path)
                if artwork:
                    for path in artwork.paths:
                        self._cleanup_file(path)

    def _cleanup_file(self, file_path: str) -> None:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup {file_path}: {e}")
