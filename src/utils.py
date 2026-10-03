"""Utility functions for Telegram Forwarder."""
import random
import asyncio
from typing import Optional


def get_random_delay(min_delay: float, max_delay: float) -> float:
    """
    Generate a random delay within the specified range.
    
    Args:
        min_delay: Minimum delay in seconds
        max_delay: Maximum delay in seconds
    
    Returns:
        Random delay value between min_delay and max_delay (inclusive)
    """
    if min_delay > max_delay:
        raise ValueError(f"min_delay ({min_delay}) cannot be greater than max_delay ({max_delay})")
    
    if min_delay == max_delay:
        return min_delay
    
    return random.uniform(min_delay, max_delay)


async def async_sleep_with_delay(min_delay: float, max_delay: float) -> float:
    """
    Sleep for a random duration within the specified range.
    
    Args:
        min_delay: Minimum delay in seconds
        max_delay: Maximum delay in seconds
    
    Returns:
        The actual delay that was used
    """
    delay = get_random_delay(min_delay, max_delay)
    await asyncio.sleep(delay)
    return delay


def format_progress_message(task_id: str, forwarded: int, total: Optional[int] = None) -> str:
    """Format a progress message for display."""
    if total is not None:
        return f"[{task_id}] Forwarded {forwarded}/{total} messages"
    return f"[{task_id}] Forwarded {forwarded} messages"
