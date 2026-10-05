"""Telegram failures which require an operator action rather than a retry."""
from telethon import errors

PERMANENT_NAMES = (
    "ChatWriteForbiddenError", "ChatAdminRequiredError", "ChannelPrivateError",
    "UserBannedInChannelError", "ChatSendMediaForbiddenError", "ChatSendPhotosForbiddenError",
    "ChatSendVideosForbiddenError", "PeerIdInvalidError", "MessageIdInvalidError",
    "MediaCaptionTooLongError", "MediaEmptyError", "PhotoInvalidError", "DocumentInvalidError",
)
PERMANENT_ERRORS = tuple(getattr(errors, name) for name in PERMANENT_NAMES if hasattr(errors, name))


class PermanentTransferError(RuntimeError):
    pass


def is_permanent_error(error):
    return isinstance(error, (PermanentTransferError,) + PERMANENT_ERRORS)
