"""Shared offline factories; importing these helpers never collects test modules."""
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from PIL import Image
from telethon import types

from tg_forwarder.config.startup import StartupConfig
from tg_forwarder.tasks.manager import TaskManager
from tg_forwarder.telegram.client import TelegramClientWrapper
from tg_forwarder.telegram.sender import ReliableSender
from tg_forwarder.telegram.transfer import ParallelTransfer

VALUES = {"TG_API_ID": "12345", "TG_API_HASH": "a" * 32, "TG_PHONE": "+12345678901"}


def startup(tmp_path, **values):
    return StartupConfig.from_values(dict(VALUES, **values), project_root=tmp_path)


def manager(state):
    cm, tracker, _ = state
    return TaskManager(SimpleNamespace(set_progress_tracker=Mock(), ensure_ready=AsyncMock()), cm, tracker, temp_dir=cm.get_config().temp_dir)


def jpeg(width=640, height=480):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(output, "JPEG")
    return output.getvalue()


def video(message_id=10, reference=b"old", cover=False, thumbs=None):
    document = types.Document(
        id=100 + message_id, access_hash=1, file_reference=reference, date=None,
        mime_type="video/mp4", size=1000, dc_id=2,
        attributes=[types.DocumentAttributeVideo(duration=5, w=640, h=480)],
        thumbs=thumbs if thumbs is not None else [types.PhotoSize("m", 320, 240, 1000)],
    )
    photo = types.Photo(
        id=300, access_hash=2, file_reference=reference, date=None,
        sizes=[types.PhotoSize("x", 800, 600, 5000)], dc_id=2,
    ) if cover else None
    return SimpleNamespace(
        id=message_id, input_chat=types.InputPeerChannel(123, 1), chat_id=-100123,
        media=types.MessageMediaDocument(document=document, video_cover=photo),
        text="caption", message="caption",
    )


def wrapper(*, database=None):
    client = TelegramClientWrapper(1, "hash",
        sender_factory=(lambda raw: ReliableSender(raw, database)) if database is not None else None,
        transfer_factory=ParallelTransfer if database is not None else None)
    client._client = AsyncMock()
    return client
