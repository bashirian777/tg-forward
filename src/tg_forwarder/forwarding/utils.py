"""Utility functions for Telegram Forwarder."""
import random


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
