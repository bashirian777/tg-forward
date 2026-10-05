"""Persist Telegram request identities across transport retries."""
import base64
import hashlib
import secrets
import time
from telethon import functions, types, utils
from telethon.errors import RandomIdDuplicateError
from telethon.extensions import BinaryReader, markdown


def encode_media(media):
    return base64.b64encode(bytes(media)).decode("ascii")


def decode_media(data):
    with BinaryReader(base64.b64decode(data)) as reader:
        return reader.tgread_object()


class ReliableSender:
    def __init__(self, client, database):
        self.client = client
        self.db = database

    async def send(self, entity, media, *, task_id, message_ids, caption=None, reply_to=None, send_as=None, source=None):
        peer = await self.client.get_input_entity(entity)
        task = self.db.get_task(task_id)
        identity = [task.get("source_channel"), task.get("target_channel"), message_ids, reply_to, bool(source)]
        key = hashlib.sha256(repr(identity).encode()).hexdigest()
        intent = self.db.get_intent(task_id, key)
        if intent and intent.get("sent"):
            return True
        items = media if isinstance(media, list) else [media]
        if not intent:
            intent = {"random_ids": [secrets.randbits(63) for _ in items], "sent": False, "message_ids": message_ids}
            if isinstance(caption, types.TextWithEntities):
                intent["caption"] = encode_media(caption)
            intent["updated_at"] = time.time()
            self.db.save_intent(task_id, key, intent)
        if source:
            request = functions.messages.ForwardMessagesRequest(
                from_peer=await self.client.get_input_entity(source), id=message_ids,
                random_id=intent["random_ids"], to_peer=peer,
                top_msg_id=reply_to,
            )
        else:
            prepared = []
            for item in items:
                if isinstance(item, (types.InputMediaUploadedPhoto, types.InputMediaUploadedDocument)):
                    result = await self.client(functions.messages.UploadMediaRequest(peer, item))
                    converted = utils.get_input_media(getattr(result, "document", None) or result.photo)
                    if isinstance(item, types.InputMediaUploadedDocument):
                        converted.video_cover = item.video_cover
                        converted.video_timestamp = item.video_timestamp
                    prepared.append(converted)
                else:
                    prepared.append(item)
            if intent.get("caption"):
                caption = decode_media(intent["caption"])
            text, entities = ((caption.text, caption.entities) if isinstance(caption, types.TextWithEntities)
                              else markdown.parse(caption or ""))
            reply = types.InputReplyToMessage(reply_to) if reply_to else None
            send_peer = await self.client.get_input_entity(send_as) if send_as else None
            if len(prepared) == 1:
                request = functions.messages.SendMediaRequest(peer, prepared[0], message=text,
                    random_id=intent["random_ids"][0], entities=entities, reply_to=reply, send_as=send_peer)
            else:
                request = functions.messages.SendMultiMediaRequest(peer,
                    [types.InputSingleMedia(item, random_id=random_id, message=text if i == 0 else "", entities=entities if i == 0 else [])
                     for i, (item, random_id) in enumerate(zip(prepared, intent["random_ids"]))],
                    reply_to=reply, send_as=send_peer)
        try:
            await self.client(request)
        except RandomIdDuplicateError:
            # This exact persisted identity was already accepted by Telegram.
            # Never issue a new ID merely because the first response was lost.
            pass
        intent["sent"] = True
        self.db.save_intent(task_id, key, intent)
        return True
