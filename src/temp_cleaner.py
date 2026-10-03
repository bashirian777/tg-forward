"""Cleanup of owned, inactive transfer directories."""
from .workspace import WorkspaceStore


def cleanup_temp_dir(temp_dir="temp", max_age_hours=24.0):
    return WorkspaceStore(temp_dir).cleanup(max_age_hours=max_age_hours)
