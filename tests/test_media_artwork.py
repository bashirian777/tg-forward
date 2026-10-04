"""Offline checks for artwork preservation and temporary file ownership."""
import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image
from telethon import functions, types
from telethon.errors import FileReferenceExpiredError

from tg_forwarder.telegram.artwork import MediaArtwork, normalize_artwork
from tg_forwarder.forwarding.handler import MessageHandler
from tg_forwarder.telegram.client import TelegramClientWrapper
from tg_forwarder.runtime.cleanup import cleanup_temp_dir


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


def wrapper():
    client = TelegramClientWrapper(1, "hash")
    client._client = AsyncMock()
    return client


def test_thumbnail_is_small_valid_jpeg_even_for_noisy_image():
    source = Image.effect_noise((1600, 900), 100).convert("RGB")
    output = io.BytesIO()
    source.save(output, "PNG")
    encoded = normalize_artwork(output.getvalue())
    assert len(encoded) < 20 * 1024
    with Image.open(io.BytesIO(encoded)) as result:
        assert result.format == "JPEG"
        assert result.width <= 320 and result.height <= 320
        assert abs(result.width / result.height - 1600 / 900) < 0.02


@pytest.mark.asyncio
async def test_refresh_reference_and_retry_thumbnail(tmp_path):
    client = wrapper()
    old, initial, fresh = video(), video(reference=b"initial"), video(reference=b"fresh")
    client._client.get_messages.side_effect = [initial, fresh]
    seen = []

    async def download(message, **kwargs):
        seen.append(message.media.document.file_reference)
        if len(seen) == 1:
            raise FileReferenceExpiredError(None)
        return jpeg()

    client._client.download_media.side_effect = download
    artwork = await client.prepare_media_artwork(old, str(tmp_path), "task")
    assert artwork.message is fresh
    assert seen == [b"initial", b"fresh"]
    assert artwork.thumb and not artwork.cover
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.asyncio
async def test_invalid_larger_thumbnail_falls_back_to_embedded_preview(tmp_path):
    client = wrapper()
    message = video(thumbs=[types.PhotoSize("x", 640, 480, 3000), types.PhotoStrippedSize("i", b"preview")])
    client._client.get_messages.return_value = message
    client._client.download_media.side_effect = [b"corrupt", jpeg(40, 30)]
    artwork = await client.prepare_media_artwork(message, str(tmp_path))
    assert artwork.thumb
    calls = client._client.download_media.call_args_list
    assert [call.kwargs["thumb"].type for call in calls] == ["x", "i"]
    assert all(call.kwargs["file"] is bytes for call in calls)
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.asyncio
async def test_unusable_artwork_leaves_no_empty_files(tmp_path, caplog):
    client = wrapper()
    message = video()
    client._client.get_messages.return_value = message
    client._client.download_media.return_value = b""
    artwork = await client.prepare_media_artwork(message, str(tmp_path))
    assert artwork.paths == []
    assert list(tmp_path.iterdir()) == []
    assert "No usable original artwork" in caplog.text


@pytest.mark.asyncio
async def test_cover_also_produces_thumbnail_when_document_has_none(tmp_path):
    client = wrapper()
    message = video(cover=True, thumbs=[])
    client._client.get_messages.return_value = message
    client._client.download_media.return_value = jpeg(1200, 800)
    artwork = await client.prepare_media_artwork(message, str(tmp_path))
    assert artwork.cover and artwork.thumb
    with Image.open(artwork.cover) as cover, Image.open(artwork.thumb) as thumb:
        assert cover.size == (1200, 800)
        assert max(thumb.size) <= 320
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.asyncio
async def test_cancellation_during_preparation_removes_already_saved_cover(tmp_path):
    client = wrapper()
    message = video(cover=True)
    client._client.get_messages.return_value = message
    client._client.download_media.side_effect = [jpeg(), asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await client.prepare_media_artwork(message, str(tmp_path))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_edited_video_is_not_paired_with_new_artwork(tmp_path):
    client = wrapper()
    old, edited = video(), video(message_id=20)
    client._client.get_messages.return_value = edited
    client._client.download_media.return_value = jpeg()
    artwork = await client.prepare_media_artwork(old, str(tmp_path))
    assert artwork.message is old
    assert client._client.download_media.call_args.args[0] is old


def test_copy_preserves_separate_cover():
    message = video(cover=True)
    media = TelegramClientWrapper.input_media_with_cover(message)
    assert isinstance(media, types.InputMediaDocument)
    assert media.video_cover.id == message.media.video_cover.id
    assert bytes(media)


@pytest.mark.asyncio
async def test_upload_and_album_conversion_preserve_cover_and_remove_local_sources(tmp_path):
    client = wrapper()
    message = video(cover=True)
    source, thumb, cover = (tmp_path / name for name in ("video.mp4", "thumb.jpg", "cover.jpg"))
    source.write_bytes(b"video")
    thumb.write_bytes(jpeg())
    cover.write_bytes(jpeg())
    handles = [types.InputFile(1, 1, "video.mp4", ""), types.InputFile(2, 1, "thumb.jpg", ""), types.InputFile(3, 1, "cover.jpg", "")]
    client._client.upload_file.side_effect = handles
    client._client.side_effect = [
        SimpleNamespace(photo=message.media.video_cover),
        SimpleNamespace(document=message.media.document),
    ]
    media = await client.upload_media_for_album(
        str(source), attributes=message.media.document.attributes,
        thumb=str(thumb), cover=str(cover), entity="target",
    )
    assert list(tmp_path.iterdir()) == []
    assert media.thumb is handles[1]
    assert media.video_cover.id == 300
    await client.send_uploaded_album("target", [media], reply_to=8, caption="caption")
    sent = client._client.send_file.call_args.args[1][0]
    assert isinstance(sent, types.InputMediaDocument)
    assert sent.video_cover.id == 300
    assert bytes(sent)
    assert client._client.send_file.call_args.kwargs["reply_to"] == 8
    assert all(isinstance(call.args[0], functions.messages.UploadMediaRequest) for call in client._client.call_args_list)


@pytest.mark.asyncio
async def test_single_upload_attaches_both_cover_and_thumb(tmp_path):
    client = wrapper()
    message = video(cover=True)
    client.get_entity = AsyncMock(return_value="target")
    source, thumb, cover = (tmp_path / name for name in ("video.mp4", "thumb.jpg", "cover.jpg"))
    source.write_bytes(b"video")
    thumb.write_bytes(jpeg())
    cover.write_bytes(jpeg())
    client._client.upload_file.side_effect = [types.InputFile(i, 1, "file", "") for i in range(3)]
    client._client.return_value = SimpleNamespace(photo=message.media.video_cover)
    assert await client.send_file_with_metadata(
        1, str(source), attributes=message.media.document.attributes,
        thumb=str(thumb), cover=str(cover), reply_to=9,
    )
    sent = client._client.send_file.call_args.args[1]
    assert isinstance(sent, types.InputMediaUploadedDocument)
    assert sent.thumb is not None and sent.video_cover.id == 300
    assert len(list(tmp_path.iterdir())) == 3  # Handler owns cleanup for singles.


@pytest.mark.parametrize("album", [False, True])
@pytest.mark.parametrize("outcome", ["success", "download_failure", "send_failure", "cancel"])
@pytest.mark.asyncio
async def test_handlers_cache_artwork_before_download_and_clean_every_exit(tmp_path, album, outcome):
    client = wrapper()
    client.get_entity = AsyncMock(return_value="target")
    client._progress_tracker = Mock()
    message = video()
    events = []

    async def prepare(*args):
        events.append("artwork")
        thumb, cover = tmp_path / "thumb.jpg", tmp_path / "cover.jpg"
        thumb.write_bytes(jpeg())
        cover.write_bytes(jpeg())
        return MediaArtwork(message, str(thumb), str(cover))

    async def download(*args, **kwargs):
        events.append("download")
        assert (tmp_path / "thumb.jpg").exists()
        assert (tmp_path / "cover.jpg").exists()
        if outcome == "download_failure":
            raise RuntimeError("download failed")
        if outcome == "cancel":
            raise asyncio.CancelledError()
        source = tmp_path / "video.mp4"
        source.write_bytes(b"video")
        return str(source)

    client.prepare_media_artwork = prepare
    client.download_media = download
    client.send_file_with_metadata = AsyncMock(return_value=outcome != "send_failure")
    client.upload_media_for_album = AsyncMock(return_value=types.InputMediaUploadedDocument(
        types.InputFile(1, 1, "video.mp4", ""), "video/mp4", message.media.document.attributes,
    ))
    client.send_uploaded_album = AsyncMock(return_value=True)
    if outcome == "send_failure":
        client.send_uploaded_album.side_effect = RuntimeError("album send failed")
    handler = MessageHandler(client, str(tmp_path), min_free_disk_mb=0)
    operation = handler._download_and_send_album([message], 1, task_id="task") if album else handler.download_and_send(message, 1, task_id="task")
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await operation
    else:
        result = await operation
        assert (result.success if album else result) == (outcome == "success")
    assert events == ["artwork", "download"]
    assert list(tmp_path.iterdir()) == []


def test_startup_cleanup_also_removes_stale_thumbnails_and_covers(tmp_path):
    import time
    from tg_forwarder.storage.workspace import WorkspaceStore, OWNER_FILE, atomic_json
    store = WorkspaceStore(tmp_path)
    path = store.open("task", -100123, [1])
    for name in ("video.mp4", "thumb_task.jpg", "cover_task.jpg"):
        (path / name).write_bytes(b"old")
    store.release(path)
    atomic_json(path / OWNER_FILE, {"task_id": "task", "updated_at": time.time() - 7200})
    active = store.open("active", -100123, [2])
    (active / "cover_active.jpg").write_bytes(b"active")
    unrelated = tmp_path / "unrelated.jpg"
    unrelated.write_bytes(b"private")
    result = cleanup_temp_dir(str(tmp_path), max_age_hours=1)
    assert result["removed"] == 3
    assert not path.exists()
    assert (active / "cover_active.jpg").exists()
    assert unrelated.exists()
    store.release(active)
