"""Compatibility imports for callers of the old forwarding error module."""
from tg_forwarder.telegram.errors import PermanentTransferError, is_permanent_error

__all__ = ["PermanentTransferError", "is_permanent_error"]
