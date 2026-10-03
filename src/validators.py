"""Validation functions for Telegram Forwarder."""
from typing import Tuple, Optional


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def validate_channel_id(channel_id: int) -> Tuple[bool, Optional[str]]:
    """
    Validate a Telegram channel/group ID.
    
    Telegram channel/group IDs are negative integers.
    Supergroups and channels start with -100.
    Regular groups are negative but don't start with -100.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(channel_id, int):
        return False, f"Channel ID must be an integer, got {type(channel_id).__name__}"
    
    # Channel IDs should be negative for groups/channels
    # Positive IDs are for users
    if channel_id >= 0:
        return False, "Channel/group ID must be negative"
    
    return True, None


def validate_delay_range(min_delay: float, max_delay: float) -> Tuple[bool, Optional[str]]:
    """
    Validate delay range configuration.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(min_delay, (int, float)):
        return False, f"min_delay must be a number, got {type(min_delay).__name__}"
    
    if not isinstance(max_delay, (int, float)):
        return False, f"max_delay must be a number, got {type(max_delay).__name__}"
    
    if min_delay < 0:
        return False, "min_delay cannot be negative"
    
    if max_delay < 0:
        return False, "max_delay cannot be negative"
    
    if min_delay > max_delay:
        return False, f"min_delay ({min_delay}) cannot be greater than max_delay ({max_delay})"
    
    return True, None


def validate_task_id(task_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate task ID format.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(task_id, str):
        return False, f"task_id must be a string, got {type(task_id).__name__}"
    
    if not task_id.strip():
        return False, "task_id cannot be empty"
    
    return True, None
