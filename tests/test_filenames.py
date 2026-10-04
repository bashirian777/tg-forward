"""Progress displays the original Unicode name while paths stay safe and stable."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from telethon import types

from src.transfer import ParallelTransfer
from src.telegram_client import _safe_name
from tests.test_integrity import state
from tests.test_media_artwork import video, wrapper


@pytest.mark.asyncio
async def test_chinese_filename_survives_download_and_upload_progress(state, tmp_path, monkeypatch):
    _, tracker, _ = state
    client = wrapper()
    client.set_progress_tracker(tracker)
    message = video(message_id=23)
    original_name = "中文视频测试 🎬 3P.mp4"
    message.media.document.attributes.append(types.DocumentAttributeFilename(original_name))
    expected_path = tmp_path / ("23_" + _safe_name(original_name))

    async def download(source, destination, progress):
        assert Path(destination) == expected_path
        progress(500, 1000)
        assert tracker.get_transfer("task")["filename"] == original_name
        Path(destination).write_bytes(b"video")
        progress(1000, 1000)
        return str(destination)

    monkeypatch.setattr(ParallelTransfer, "download", AsyncMock(side_effect=download))
    path = await client.download_media(message, str(tmp_path), task_id="task", clear_progress=False)
    assert tracker.db.get_transfer("task")["filename"] == original_name

    async def upload(source, progress_callback):
        assert Path(source) == expected_path
        progress_callback(5, 5)
        return types.InputFile(1, 1, expected_path.name, "md5")

    client.upload_source = AsyncMock(side_effect=upload)
    uploaded = await client.upload_media_for_album(path, attributes=message.media.document.attributes,
        task_id="task", cleanup_after_upload=False)
    transfer = tracker.db.get_transfer("task")
    assert transfer["type"] == "upload"
    assert transfer["filename"] == original_name
    assert any(isinstance(attr, types.DocumentAttributeFilename) and attr.file_name == original_name
        for attr in uploaded.attributes)


@pytest.mark.asyncio
async def test_unsafe_source_name_is_displayed_without_becoming_a_path(state, tmp_path, monkeypatch):
    _, tracker, _ = state
    client = wrapper()
    client.set_progress_tracker(tracker)
    message = video()
    original_name = "../../目录\\中文视频.mp4"
    message.media.document.attributes.append(types.DocumentAttributeFilename(original_name))

    async def fail_download(source, destination, progress):
        assert Path(destination).parent == tmp_path
        assert "/" not in Path(destination).name and "\\" not in Path(destination).name
        progress(1, 1000)
        raise OSError("interrupted")

    monkeypatch.setattr(ParallelTransfer, "download", AsyncMock(side_effect=fail_download))
    with pytest.raises(OSError, match="interrupted"):
        await client.download_media(message, str(tmp_path), task_id="task")
    transfer = tracker.db.get_transfer("task")
    assert transfer["filename"] == original_name
    assert transfer["error_filename"] == original_name
