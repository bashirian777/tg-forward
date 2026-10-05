"""Progress reporting cannot silently change transport or workspace ownership."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telethon import types

from tg_forwarder.forwarding.handler import MessageHandler
from tg_forwarder.runtime.service import create_user_client
from tg_forwarder.storage.workspace import WorkspaceStore
from tests.support import startup, video, wrapper


@pytest.mark.asyncio
async def test_progress_tracker_only_reports_telemetry(state):
    _, tracker, _ = state
    client = wrapper()
    client.set_progress_tracker(tracker)
    media = types.InputMediaPhoto(types.InputPhoto(1, 2, b"ref"))
    assert await client.send_existing_media("target", media, task_id="task", message_ids=[1])
    client._client.send_file.assert_awaited_once()
    client._client.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_sender_does_not_require_a_database_backed_tracker(state):
    client = wrapper()
    sender = SimpleNamespace(send=AsyncMock(return_value=True))
    factory = Mock(return_value=sender)
    client.sender_factory = factory
    client.set_progress_tracker(SimpleNamespace(update_transfer=Mock()))
    media = types.InputMediaPhoto(types.InputPhoto(1, 2, b"ref"))
    assert await client.send_existing_media("target", media, task_id="task", message_ids=[1])
    factory.assert_called_once_with(client._client)
    sender.send.assert_awaited_once()
    client._client.send_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_transfer_factory_works_without_progress_tracker(tmp_path):
    client = wrapper()
    transfer = SimpleNamespace(download=AsyncMock(return_value=str(tmp_path / "video.mp4")))
    factory = Mock(return_value=transfer)
    client.transfer_factory = factory
    telemetry = SimpleNamespace(update_download_progress=Mock(), clear_download_progress=Mock())
    client.set_progress_tracker(telemetry)
    assert await client.download_media(video(), str(tmp_path), task_id="task") == str(tmp_path / "video.mp4")
    factory.assert_called_once_with(client._client, 4, 4)
    transfer.download.assert_awaited_once()
    client._client.download_media.assert_not_awaited()


def test_service_composition_explicitly_configures_reliable_transport(state, tmp_path):
    config, _, _ = state
    deployment = startup(tmp_path)
    standalone = create_user_client(deployment)
    managed = create_user_client(deployment, database=config.db)
    assert standalone.sender_factory is None and standalone.transfer_factory is None
    assert managed.sender_factory is not None and managed.transfer_factory is not None
    assert managed.sender_factory(AsyncMock()).db is config.db


@pytest.mark.asyncio
async def test_workspace_retention_is_explicit_even_with_custom_telemetry(tmp_path):
    client = wrapper()
    client.get_entity = AsyncMock(return_value="target")
    client.send_existing_media = AsyncMock(side_effect=TimeoutError("response lost"))
    store = WorkspaceStore(tmp_path)
    handler = MessageHandler(client, str(tmp_path), min_free_disk_mb=0,
        progress_tracker=SimpleNamespace(), workspace_store=store)
    with pytest.raises(TimeoutError):
        await handler.forward_message_group([video()], -1001, -1002, task_id="task")
    assert store.stats()["workspaces"] == 1
    assert store.stats()["active"] == 0


@pytest.mark.asyncio
async def test_upload_ownership_is_an_argument_not_a_file_marker(tmp_path):
    client = wrapper()
    store = WorkspaceStore(tmp_path)
    owned = store.open("task", -1001, [1])
    source = owned / "photo.jpg"
    source.write_bytes(b"photo")
    client._client.upload_file.return_value = types.InputFile(1, 1, "photo.jpg", "")
    try:
        media = await client.upload_media_for_album(str(source), entity="target", cleanup_after_upload=True)
        assert isinstance(media, types.InputMediaUploadedPhoto)
        assert not source.exists()
        client._client.assert_not_awaited()
    finally:
        store.release(owned)

    source = tmp_path / "retained.jpg"
    source.write_bytes(b"photo")
    client._client.return_value = SimpleNamespace(photo=types.Photo(1, 2, b"ref", None, [], 1))
    media = await client.upload_media_for_album(str(source), entity="target",
        cleanup_after_upload=False, persist_media=True)
    assert isinstance(media, types.InputMediaPhoto)
    assert source.exists()
    client._client.assert_awaited_once()
