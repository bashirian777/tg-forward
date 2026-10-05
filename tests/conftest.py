"""Shared pytest state, confined to each test's temporary directory."""
from dataclasses import replace

import pytest

from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.storage.progress_store import ProgressTracker
from tg_forwarder.tasks.models import ForwardTask


@pytest.fixture
def state(tmp_path):
    cm = ConfigManager(str(tmp_path / "forwarder.db"), project_root=tmp_path)
    task = ForwardTask("task", -1001111111111, -1002222222222, 0, 0)
    cm.initialize()
    cm.save_app_config(replace(cm.get_config(), temp_dir=str(tmp_path / "temp")))
    cm.add_task(task)
    return cm, ProgressTracker(database=cm.db), task
