"""Telegram client wrapper using Telethon."""
import asyncio
import os
import logging
import re
import time
import uuid
from typing import List, Optional, Any
from telethon import TelegramClient, functions, types, utils
from telethon.tl.types import Message, PeerChannel, PeerChat, InputMediaUploadedDocument, DocumentAttributeFilename
from telethon.errors import (
    SessionPasswordNeededError, FloodWaitError, FileReferenceExpiredError,
    FilerefUpgradeNeededError,
)

from .artwork import MediaArtwork, artwork_sizes, normalize_artwork
from .errors import is_permanent_error, PermanentTransferError
from tg_forwarder.tasks.errors import RuntimeUnavailable
from tg_forwarder.config.paths import DEFAULT_SESSION_PATH, PROJECT_ROOT
from pathlib import Path


logger = logging.getLogger(__name__)


def _safe_name(value: str) -> str:
    """Sanitize a string for use inside a file name."""
    return re.sub(r'[^A-Za-z0-9_.-]', '_', str(value))


def _media_filename(attributes, fallback: str) -> str:
    """Keep the source name for progress and errors, independent of disk paths."""
    for attribute in attributes or []:
        if isinstance(attribute, DocumentAttributeFilename) and attribute.file_name:
            return attribute.file_name
    return fallback


class TelegramSessionError(ValueError):
    """An expected login/account problem with a safe operator-facing message."""


class TelegramClientWrapper:
    """Wrapper around Telethon client for Telegram operations."""

    def __init__(self, api_id: int, api_hash: str, session_name: str = str(PROJECT_ROOT / DEFAULT_SESSION_PATH),
                 proxy: dict = None, *, sender_factory=None, transfer_factory=None,
                 metrics_callback=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.proxy = proxy  # {"proxy_type": "socks5", "addr": "127.0.0.1", "port": 1080}
        self._client: Optional[TelegramClient] = None
        self._progress_tracker = None  # Telemetry only; it never selects a transport.
        self.sender_factory = sender_factory
        self.transfer_factory = transfer_factory
        self.metrics_callback = metrics_callback
        self.download_workers = 4
        self.upload_workers = 4
        self.connection_status = {"state": "disconnected", "message": "Telegram 尚未连接"}
        self._topic_sources = {}
        self._topic_names = {}
        self._caption_limit = (0, 1024)

    def set_progress_tracker(self, tracker):
        """Set progress tracker for download/upload progress updates."""
        self._progress_tracker = tracker

    async def connect(self) -> bool:
        """Connect to Telegram servers."""
        if self._client is None:
            kwargs = {
                "request_retries": 5,
                "connection_retries": 5,
            }
            if self.proxy:
                kwargs["proxy"] = self.proxy

            Path(self.session_name).parent.mkdir(parents=True, exist_ok=True)
            self._client = TelegramClient(
                self.session_name,
                self.api_id,
                self.api_hash,
                **kwargs
            )

        await self._client.connect()
        return self._client.is_connected()

    async def disconnect(self) -> None:
        """Disconnect from Telegram servers."""
        if self._client:
            await self._client.disconnect()

    async def is_authorized(self) -> bool:
        """Check if the client is authorized."""
        if self._client is None:
            return False
        return await self._client.is_user_authorized()

    async def logout(self):
        if self._client:
            await self._client.log_out()
            self._client = None

    async def validate_account(self, phone):
        """Never silently reuse a session belonging to another configured phone."""
        me = await self._client.get_me()
        if not me or str(getattr(me, "phone", "")).lstrip("+") != phone.lstrip("+"):
            raise TelegramSessionError("Telegram 会话与 TG_PHONE 不一致，请停止服务后执行 login --relogin")

    async def ensure_ready(self):
        if self.connection_status["state"] != "ready" or not self._client or not self._client.is_connected():
            raise RuntimeUnavailable(self.connection_status["message"] if self.connection_status["state"] != "ready" else "Telegram 连接已断开，请稍后再试")

    async def login(self, phone: str, code: Optional[str] = None,
                    password: Optional[str] = None) -> bool:
        """
        Login to Telegram with phone number.
        """
        if self._client is None:
            await self.connect()

        if await self.is_authorized():
            return True

        if code is None:
            await self._client.send_code_request(phone)
            return False

        try:
            await self._client.sign_in(phone, code)
            return True
        except SessionPasswordNeededError:
            if password is None:
                raise ValueError("2FA password required")
            await self._client.sign_in(password=password)
            return True

    async def get_entity(self, channel_id: int) -> Any:
        """Get entity (channel/group) information."""
        if channel_id < 0:
            abs_id = abs(channel_id)
            id_str = str(abs_id)

            if id_str.startswith("100") and len(id_str) > 10:
                peer_id = int(id_str[3:])
            else:
                peer_id = abs_id

            logger.debug(f"Trying to get entity: original={channel_id}, peer_id={peer_id}")

            try:
                entity = await self._client.get_entity(PeerChannel(peer_id))
                logger.debug(f"Got entity via PeerChannel: {entity}")
                return entity
            except Exception as e1:
                logger.debug(f"PeerChannel({peer_id}) failed: {e1}")

            try:
                entity = await self._client.get_entity(PeerChat(peer_id))
                logger.debug(f"Got entity via PeerChat: {entity}")
                return entity
            except Exception as e2:
                logger.debug(f"PeerChat({peer_id}) failed: {e2}")

            try:
                full_id = int(f"-100{peer_id}")
                entity = await self._client.get_entity(full_id)
                logger.debug(f"Got entity via full_id: {entity}")
                return entity
            except Exception as e3:
                logger.debug(f"Full ID {full_id} failed: {e3}")

            return await self._client.get_entity(channel_id)
        else:
            return await self._client.get_entity(channel_id)

    async def get_source_topic_name(self, channel_id: int, message: Message) -> Optional[str]:
        """Read the current forum topic name, never treating ordinary replies as topics."""
        now = time.monotonic()
        cached = self._topic_sources.get(channel_id)
        if cached is None or cached[0] <= now:
            try:
                entity = await self.get_entity(channel_id)
            except FloodWaitError:
                raise
            except Exception as error:
                logger.warning("Could not read source forum %s: %s", channel_id, error)
                self._topic_sources[channel_id] = (now + 60, None)
                return None
            self._topic_sources[channel_id] = (now + 300, entity)
        else:
            entity = cached[1]
        if not getattr(entity, "forum", False):
            return None
        reply = getattr(message, "reply_to", None)
        topic_id = ((getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", None))
                    if getattr(reply, "forum_topic", False) else 1)
        if not topic_id:
            return None
        key = (channel_id, topic_id)
        cached = self._topic_names.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            result = await self._client(functions.messages.GetForumTopicsByIDRequest(entity, [topic_id]))
            topic = next((topic for topic in result.topics if topic.id == topic_id), None)
            name = getattr(topic, "title", None)
            name = " ".join(name.split()) if isinstance(name, str) else None
        except FloodWaitError:
            raise
        except Exception as error:
            logger.warning("Could not read source topic %s/%s: %s", channel_id, topic_id, error)
            name = None
        self._topic_names[key] = (time.monotonic() + (300 if name else 60), name or None)
        return name or None

    async def get_caption_limit(self) -> int:
        """Use Telegram's caption limit; retain a conservative limit if unavailable."""
        if self._caption_limit[0] <= time.monotonic():
            limit = 1024
            try:
                config = await self._client(functions.help.GetConfigRequest())
                if type(config.caption_length_max) is int and config.caption_length_max > 0:
                    limit = config.caption_length_max
            except FloodWaitError:
                raise
            except Exception:
                pass
            self._caption_limit = (time.monotonic() + 300, limit)
        return self._caption_limit[1]

    async def get_messages(self, channel_id: int, min_id: int = 0,
                          limit: int = 100) -> List[Message]:
        """Get messages from a channel/group."""
        try:
            logger.debug(f"Getting entity for channel {channel_id}")
            entity = await self.get_entity(channel_id)
            logger.debug(f"Fetching messages, min_id={min_id}, limit={limit}")
            messages = await self._client.get_messages(
                entity,
                limit=limit,
                min_id=min_id,
                reverse=True
            )
            logger.debug(f"Got {len(messages)} messages")
            return list(messages)
        except Exception as e:
            logger.error(f"Error getting messages from {channel_id}: {e}")
            raise

    async def send_existing_media(self, entity, media, *, task_id=None, message_ids=None, caption=None, reply_to=None, send_as=None, source=None):
        tracker = self._progress_tracker
        if self.sender_factory is not None and task_id:
            if tracker:
                tracker.update_transfer(task_id, {"state": "sending", "speed_str": "等待 Telegram 确认"})
            return await self.sender_factory(self._client).send(
                entity, media, task_id=task_id, message_ids=message_ids,
                caption=caption, reply_to=reply_to, send_as=send_as, source=source)
        if source:
            await self._client.forward_messages(entity, message_ids, source)
        else:
            kwargs = ({"caption": caption.text, "formatting_entities": caption.entities, "parse_mode": None}
                      if isinstance(caption, types.TextWithEntities) else {"caption": caption})
            if reply_to:
                kwargs["reply_to"] = reply_to
            if send_as:
                kwargs["send_as"] = await self.get_entity(send_as)
            await self._client.send_file(entity, media, **kwargs)
        return True

    async def forward_message(self, from_channel: int, to_channel: int,
                             message_id: int) -> bool:
        """Forward a message from one channel to another."""
        try:
            from_entity = await self.get_entity(from_channel)
            to_entity = await self.get_entity(to_channel)
            await self._client.forward_messages(to_entity, message_id, from_entity)
            return True
        except Exception:
            return False

    async def download_media(self, message: Message, path: str = "temp",
                            task_id: str = None, file_index: int = 1,
                            total_files: int = 1, clear_progress: bool = True) -> Optional[str]:
        """
        Download media from a message with progress tracking.

        Args:
            message: Message containing media
            path: Directory to save the file
            task_id: Task ID for progress tracking
        """
        if not message.media:
            return None

        os.makedirs(path, exist_ok=True)

        # Get file size and name for progress
        total_size = 0
        filename = ""
        if hasattr(message.media, 'document') and message.media.document:
            total_size = message.media.document.size
            for attr in message.media.document.attributes:
                if hasattr(attr, 'file_name'):
                    filename = attr.file_name
                    break
        elif hasattr(message.media, 'photo') and message.media.photo:
            if message.media.photo.sizes:
                largest = message.media.photo.sizes[-1]
                total_size = getattr(largest, 'size', 0)
            filename = "photo.jpg"

        last_update = [0]
        message_id = message.id
        tracker = self._progress_tracker

        def progress_callback(current: int, total: int):
            """Update download progress every 10 seconds."""
            now = time.time()
            if now - last_update[0] >= 10 or current == total:
                last_update[0] = now
                if tracker and task_id:
                    tracker.update_download_progress(
                        task_id, current, total, filename, message_id,
                        file_index=file_index, total_files=total_files
                    )

        logger.debug(f"Starting download: {filename}, size: {total_size}")
        storage_filename = _safe_name(filename or f"media_{message.id}")
        if not os.path.splitext(storage_filename)[1]:
            import mimetypes
            mime = getattr(getattr(message.media, "document", None), "mime_type", "image/jpeg")
            storage_filename += mimetypes.guess_extension(mime) or ".bin"
        filename = filename or storage_filename
        destination = os.path.join(path, f"{message.id}_{storage_filename}")
        started = time.monotonic()
        try:
            document = getattr(message.media, "document", None)
            if document and self.transfer_factory is not None:
                for attempt in range(2):
                    try:
                        file_path = await self.transfer_factory(self._client, self.download_workers, self.upload_workers).download(message, destination, progress_callback)
                        break
                    except (FileReferenceExpiredError, FilerefUpgradeNeededError) as error:
                        if attempt:
                            raise PermanentTransferError("Source file reference remains invalid; inspect or skip this group") from error
                        peer = message.input_chat or message.chat_id
                        fresh = await self._client.get_messages(peer, ids=message.id)
                        fresh_doc = getattr(getattr(fresh, "media", None), "document", None)
                        if not fresh_doc or fresh_doc.id != document.id:
                            raise PermanentTransferError("Source media was deleted or replaced; inspect or skip this group") from error
                        message = fresh
                    except Exception as error:
                        # The standard downloader handles CDN redirects and
                        # verification; keep it as the compatibility fallback.
                        from telethon.client.downloads import _CdnRedirect
                        if not isinstance(error, _CdnRedirect):
                            raise
                        Path(destination + ".part").unlink(missing_ok=True)
                        Path(destination + ".download.json").unlink(missing_ok=True)
                        file_path = await self._client.download_media(message, file=destination, progress_callback=progress_callback)
                        break
            else:
                file_path = await self._client.download_media(message, file=destination, progress_callback=progress_callback)
            if self.metrics_callback is not None and task_id:
                elapsed = time.monotonic() - started
                self.metrics_callback(task_id, {"stage": "download", "bytes": total_size,
                    "seconds": round(elapsed, 3), "workers": self.download_workers})
        except FloodWaitError:
            raise
        except Exception as error:
            if tracker and task_id:
                tracker.record_error(
                    task_id, "telegram_download", error,
                    message_id=message_id, file_index=file_index,
                    filename=filename,
                )
            logger.error(f"Download media {message_id} failed: {error}")
            raise

        # Clear download progress when done
        if tracker and task_id and clear_progress:
            tracker.clear_download_progress(task_id)

        logger.debug(f"Download complete: {file_path}")
        return file_path

    async def send_message(self, channel_id: int, text: Optional[str] = None,
                          file: Optional[str] = None) -> bool:
        """Send a message or file to a channel."""
        try:
            logger.debug(f"Getting entity for send: {channel_id}")
            entity = await self.get_entity(channel_id)
            logger.debug(f"Got entity: {entity}")

            if file:
                logger.debug(f"Sending file: {file}")
                await self._client.send_file(entity, file, caption=text)
                logger.debug("File sent successfully")
            elif text:
                logger.debug(f"Sending text: {text[:50]}...")
                await self._client.send_message(entity, text)
                logger.debug("Text sent successfully")
            else:
                logger.warning("No file or text to send")
                return False
            return True
        except Exception as e:
            logger.error(f"Send message failed: {e}")
            return False

    async def send_file_with_metadata(self, channel_id: int, file_path: str,
                                      caption: Optional[str] = None,
                                      attributes: list = None,
                                      thumb: str = None,
                                      task_id: str = None,
                                      reply_to: int = None,
                                      send_as: int = None,
                                      message_id: int = None,
                                      cover: str = None) -> bool:
        """
        Send a file with metadata (duration, dimensions, thumb) and upload progress.

        Args:
            channel_id: Target channel ID
            file_path: Path to file
            caption: Caption text
            attributes: File attributes (duration, dimensions, etc.)
            thumb: Thumbnail path
            task_id: Task ID for progress tracking
            reply_to: Topic ID for forum groups
            send_as: Channel ID to send as (for sending as channel identity)
        """
        filename = _media_filename(attributes, os.path.basename(file_path))
        tracker = self._progress_tracker
        try:
            entity = await self.get_entity(channel_id)

            media = await self.upload_media_for_album(
                file_path, attributes=attributes, thumb=thumb, cover=cover,
                task_id=task_id, message_id=message_id,
                cleanup_after_upload=False, entity=entity,
            )
            await self.send_existing_media(entity, media, task_id=task_id, message_ids=[message_id],
                caption=caption, reply_to=reply_to, send_as=send_as)
            return True
        except FloodWaitError:
            raise
        except Exception as e:
            if is_permanent_error(e):
                raise
            if tracker and task_id:
                tracker.record_error(
                    task_id, "telegram_upload_send", e,
                    message_id=message_id, filename=filename,
                )
            logger.error(f"Send file with metadata failed: {e}")
            return False

    @staticmethod
    def input_media_with_cover(message: Message):
        """Preserve a separate video cover when copying existing Telegram media."""
        media = utils.get_input_media(message.media)
        cover = getattr(message.media, "video_cover", None)
        if cover and isinstance(media, types.InputMediaDocument):
            media.video_cover = utils.get_input_photo(cover)
            media.video_timestamp = getattr(message.media, "video_timestamp", None)
        return media

    async def _refresh_artwork_message(self, message: Message) -> Message:
        """Refresh references without pairing artwork with an edited video."""
        try:
            peer = message.input_chat or message.chat_id
            if peer is None:
                return message
            fresh = await self._client.get_messages(peer, ids=message.id)
            original_doc = getattr(message.media, "document", None)
            fresh_doc = getattr(getattr(fresh, "media", None), "document", None)
            if not original_doc and not fresh_doc:
                old_photo = getattr(message.media, "photo", None)
                new_photo = getattr(getattr(fresh, "media", None), "photo", None)
                if old_photo and new_photo and old_photo.id == new_photo.id:
                    return fresh
            if original_doc and fresh_doc and original_doc.id == fresh_doc.id:
                return fresh
            logger.warning("Artwork message %s is missing or its media changed", message.id)
        except FloodWaitError:
            raise
        except Exception as error:
            logger.warning("Could not refresh artwork message %s: %s", message.id, error)
        return message

    async def _download_artwork(self, message: Message, thumbnail: bool):
        """Download static artwork, refreshing an expired reference once."""
        kind = "thumbnail" if thumbnail else "video cover"
        for attempt in range(2):
            if thumbnail:
                document = getattr(message.media, "document", None)
                media = message
                sizes = getattr(document, "thumbs", None)
            else:
                media = getattr(message.media, "video_cover", None)
                sizes = getattr(media, "sizes", None)
            expired = False
            for size in artwork_sizes(sizes, thumbnail):
                try:
                    data = await self._client.download_media(media, file=bytes, thumb=size)
                    if data:
                        data = await asyncio.to_thread(normalize_artwork, data, thumbnail)
                        return message, data
                except FloodWaitError:
                    raise
                except (FileReferenceExpiredError, FilerefUpgradeNeededError) as error:
                    logger.warning("Expired %s reference for message %s: %s", kind, message.id, error)
                    if attempt == 0:
                        expired = True
                        break
                    # Embedded/smaller previews may still work without a reference.
                except Exception as error:
                    logger.warning(
                        "Could not download/validate %s for message %s (size %s): %s",
                        kind, message.id, size.type, error,
                    )
            if not expired:
                break
            message = await self._refresh_artwork_message(message)
        return message, None

    async def prepare_media_artwork(self, message: Message, path: str = "temp",
                                    task_id: str = None) -> MediaArtwork:
        """Cache original artwork before downloading a potentially large video."""
        artwork = MediaArtwork(message)
        document = getattr(message.media, "document", None)
        if not document:
            return artwork
        artwork.message = await self._refresh_artwork_message(message)
        os.makedirs(path, exist_ok=True)
        prefix = f"{_safe_name(task_id or 'default')}_{message.id}_{uuid.uuid4().hex}"
        # Track paths before writing so cancellation and failed writes clean up too.
        pending_paths = []
        try:
            artwork.message, cover_data = await self._download_artwork(artwork.message, False)
            if cover_data:
                artwork.cover = os.path.join(path, f"cover_{prefix}.jpg")
                pending_paths.append(artwork.cover)
                with open(artwork.cover, "wb") as handle:
                    handle.write(cover_data)

            artwork.message, thumb_data = await self._download_artwork(artwork.message, True)
            if not thumb_data and cover_data:
                thumb_data = await asyncio.to_thread(normalize_artwork, cover_data, True)
            if thumb_data:
                artwork.thumb = os.path.join(path, f"thumb_{prefix}.jpg")
                pending_paths.append(artwork.thumb)
                with open(artwork.thumb, "wb") as handle:
                    handle.write(thumb_data)
            if not artwork.paths and document.mime_type.startswith("video/"):
                logger.warning("No usable original artwork for video message %s", message.id)
            return artwork
        except BaseException:
            for filename in pending_paths:
                self._cleanup_uploaded_source(filename)
            raise

    async def upload_source(self, source, progress_callback=None):
        started = time.monotonic()
        if self.transfer_factory is not None:
            result = await self.transfer_factory(self._client, self.download_workers, self.upload_workers).upload(source, progress_callback)
            logger.info("Upload %s bytes in %.2fs (%s workers)", os.path.getsize(source), time.monotonic() - started, self.upload_workers)
            return result
        kwargs = {"progress_callback": progress_callback} if progress_callback else {}
        return await self._client.upload_file(source, **kwargs)

    async def _upload_video_cover(self, entity, cover: str):
        uploaded = await self.upload_source(cover)
        result = await self._client(functions.messages.UploadMediaRequest(
            entity, types.InputMediaUploadedPhoto(file=uploaded),
        ))
        return utils.get_input_photo(result.photo)

    async def upload_media_for_album(self, file_path: str,
                                      attributes=None,
                                      thumb: str = None,
                                      task_id: str = None,
                                      file_index: int = 1,
                                      total_files: int = 1,
                                      cleanup_after_upload: bool = True,
                                      message_id: int = None,
                                      cover: str = None,
                                      entity=None,
                                      persist_media: bool = False):
        """Upload an item; callers explicitly own cleanup and reusable handles."""
        from telethon.tl.types import (
            InputMediaUploadedDocument, InputMediaUploadedPhoto,
            DocumentAttributeFilename
        )
        import mimetypes

        last_update = [0]
        tracker = self._progress_tracker
        filename = _media_filename(attributes, os.path.basename(file_path))

        def upload_progress(current: int, total: int):
            now = time.time()
            if now - last_update[0] >= 10 or current == total:
                last_update[0] = now
                if tracker and task_id:
                    tracker.update_upload_progress(
                        task_id, current, total, filename,
                        file_index=file_index, total_files=total_files
                    )


        try:
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"
            is_photo = mime_type.startswith("image/") and not file_path.lower().endswith(".gif")

            uploaded_file = await self.upload_source(file_path, progress_callback=upload_progress)
            if cleanup_after_upload:
                self._cleanup_uploaded_source(file_path)

            uploaded_thumb = None
            if thumb and os.path.exists(thumb):
                uploaded_thumb = await self.upload_source(thumb)
                if cleanup_after_upload:
                    self._cleanup_uploaded_source(thumb)

            if is_photo and not attributes:
                media = InputMediaUploadedPhoto(file=uploaded_file)
                if persist_media:
                    result = await self._client(functions.messages.UploadMediaRequest(entity, media))
                    return utils.get_input_media(result.photo)
                return media

            file_attrs = list(attributes) if attributes else []
            has_filename = any(isinstance(a, DocumentAttributeFilename) for a in file_attrs)
            if not has_filename:
                file_attrs.append(DocumentAttributeFilename(os.path.basename(file_path)))

            uploaded_cover = None
            if cover:
                uploaded_cover = await self._upload_video_cover(entity, cover)
                if cleanup_after_upload:
                    self._cleanup_uploaded_source(cover)

            media = InputMediaUploadedDocument(
                file=uploaded_file,
                mime_type=mime_type,
                attributes=file_attrs,
                thumb=uploaded_thumb,
                video_cover=uploaded_cover,
                force_file=False
            )
            if persist_media:
                result = await self._client(functions.messages.UploadMediaRequest(entity, media))
                converted = utils.get_input_media(result.document)
                converted.video_cover = media.video_cover
                converted.video_timestamp = media.video_timestamp
                return converted
            return media
        except FloodWaitError:
            raise
        except Exception as error:
            if tracker and task_id:
                tracker.record_error(
                    task_id, "telegram_album_upload", error,
                    message_id=message_id, file_index=file_index,
                    filename=filename,
                )
            logger.error(f"Upload album file {filename} failed: {error}")
            raise

    async def send_uploaded_album(self, entity, media_list: list,
                                  caption: Optional[str] = None,
                                  task_id: str = None,
                                  reply_to: int = None,
                                  send_as: int = None,
                                  message_ids: list = None) -> bool:
        """Send already-uploaded Telegram media as one album."""
        try:
            # Telethon's album conversion drops video_cover. Convert explicitly
            # and restore it on InputMediaDocument before passing the album on.
            prepared_media = []
            for media in media_list:
                if isinstance(media, types.InputMediaUploadedDocument) and media.video_cover:
                    result = await self._client(functions.messages.UploadMediaRequest(entity, media))
                    converted = utils.get_input_media(result.document, supports_streaming=True)
                    converted.video_cover = media.video_cover
                    converted.video_timestamp = media.video_timestamp
                    prepared_media.append(converted)
                else:
                    prepared_media.append(media)
            await self.send_existing_media(entity, prepared_media, task_id=task_id,
                message_ids=message_ids, caption=caption, reply_to=reply_to, send_as=send_as)
            return True
        except FloodWaitError:
            raise
        except Exception as e:
            if self._progress_tracker and task_id:
                self._progress_tracker.record_error(
                    task_id, "telegram_album_send", e,
                    message_id=(message_ids or [None])[0],
                    details="message_ids=" + repr(message_ids or []),
                )
            logger.error(f"Send uploaded album failed: {e}")
            raise

    async def send_files_with_progress(self, entity, file_paths: list,
                                       caption: Optional[str] = None,
                                       attributes_list: list = None,
                                       thumb_list: list = None,
                                       task_id: str = None,
                                       reply_to: int = None,
                                       send_as: int = None,
                                       cleanup_after_upload: bool = False) -> bool:
        """
        Send multiple files (album) with upload progress, preserving metadata.

        Args:
            entity: Target entity
            file_paths: List of file paths
            caption: Caption text
            attributes_list: List of attributes for each file
            thumb_list: List of thumbnail paths for each file
            task_id: Task ID for progress tracking
            reply_to: Topic ID for forum groups
            send_as: Channel ID to send as (for sending as channel identity)
            cleanup_after_upload: Delete each source file after Telegram accepts
                its upload. This keeps album staging bounded when source files
                are on a remote-backed mount.
        """
        from telethon.tl.types import (
            InputMediaUploadedDocument, InputMediaUploadedPhoto,
            DocumentAttributeVideo, DocumentAttributeFilename
        )
        import mimetypes

        try:
            last_update = [0]
            total_files = len(file_paths)
            tracker = self._progress_tracker
            current_file = [0]

            def upload_progress(current: int, total: int):
                now = time.time()
                if now - last_update[0] >= 10 or current == total:
                    last_update[0] = now
                    # First file has index 1; advance after a file completes.
                    idx = min(current_file[0] + 1, total_files)
                    if tracker and task_id:
                        tracker.update_upload_progress(
                            task_id, current, total,
                            f"file {idx}/{total_files}"
                        )
                    if current == total:
                        current_file[0] = idx

            # Upload every source separately when cleanup is requested, so each
            # source can be removed before the album request is sent.
            has_metadata = cleanup_after_upload or (attributes_list and any(attributes_list)) or (thumb_list and any(thumb_list))

            send_kwargs = {
                "caption": caption,
                "supports_streaming": True
            }
            if reply_to:
                send_kwargs["reply_to"] = reply_to
            if send_as:
                send_as_entity = await self.get_entity(send_as)
                send_kwargs["send_as"] = send_as_entity

            if has_metadata:
                media_list = []

                for i, file_path in enumerate(file_paths):
                    attrs = attributes_list[i] if attributes_list and i < len(attributes_list) else None
                    thumb = thumb_list[i] if thumb_list and i < len(thumb_list) else None

                    mime_type, _ = mimetypes.guess_type(file_path)
                    if not mime_type:
                        mime_type = 'application/octet-stream'

                    is_photo = mime_type.startswith('image/') and not file_path.lower().endswith('.gif')

                    uploaded_file = await self._client.upload_file(
                        file_path,
                        progress_callback=upload_progress
                    )
                    if cleanup_after_upload:
                        self._cleanup_uploaded_source(file_path)

                    uploaded_thumb = None
                    if thumb and os.path.exists(thumb):
                        uploaded_thumb = await self._client.upload_file(thumb)
                        if cleanup_after_upload:
                            self._cleanup_uploaded_source(thumb)

                    if is_photo and not attrs:
                        media_list.append(InputMediaUploadedPhoto(file=uploaded_file))
                        continue

                    file_attrs = []
                    if attrs:
                        file_attrs = list(attrs)

                    has_filename = any(isinstance(a, DocumentAttributeFilename) for a in file_attrs)
                    if not has_filename:
                        file_attrs.append(DocumentAttributeFilename(os.path.basename(file_path)))

                    media = InputMediaUploadedDocument(
                        file=uploaded_file,
                        mime_type=mime_type,
                        attributes=file_attrs,
                        thumb=uploaded_thumb,
                        force_file=False
                    )
                    media_list.append(media)

                await self._client.send_file(
                    entity,
                    media_list,
                    **send_kwargs
                )
            else:
                send_kwargs["progress_callback"] = upload_progress
                await self._client.send_file(
                    entity,
                    file_paths,
                    **send_kwargs
                )

            if tracker and task_id:
                tracker.clear_upload_progress(task_id)

            return True
        except FloodWaitError:
            raise
        except Exception as e:
            logger.error(f"Send files failed: {e}")
            raise

    @staticmethod
    def _cleanup_uploaded_source(file_path: str) -> None:
        """Remove a source file after it has been uploaded to Telegram."""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.debug("Removed uploaded source file: %s", file_path)
        except OSError as e:
            logger.warning("Failed to remove uploaded source file %s: %s", file_path, e)

    @property
    def client(self) -> Optional[TelegramClient]:
        """Get the underlying Telethon client."""
        return self._client
