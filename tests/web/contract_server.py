"""Real Flask/runtime/SQLite API with temporary state and no Telegram workers."""
from dataclasses import replace
from pathlib import Path
import os
import signal
from tempfile import TemporaryDirectory

from werkzeug.serving import make_server

from tg_forwarder.runtime.bridge import RuntimeBridge
from tg_forwarder.runtime.service import ForwarderService
from tg_forwarder.storage.config_store import ConfigManager
from tg_forwarder.storage.progress_store import ProgressTracker
from tg_forwarder.tasks.models import ForwardTask
from tg_forwarder.web.app import create_app
from tests.support import startup


class OfflineService(ForwarderService):
    async def start_background(self):
        # HTTP operations are real; no account, Bot or network worker is started.
        pass


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(prefix="tg-forward-contract-") as directory:
        root = Path(directory)
        config = ConfigManager(root / "test.db", project_root=root)
        config.initialize("测试密码")
        config.save_app_config(replace(config.get_config(), temp_dir=str(root / "temp")))
        config.add_task(ForwardTask("contract", -1001111111111, -1002222222222, 0, 0, note="契约测试"))
        progress = ProgressTracker(database=config.db)
        progress.load_progress()
        runtime = RuntimeBridge(lambda: OfflineService(startup(root), config, progress)).start()
        server = make_server("127.0.0.1", int(os.environ.get("CONTRACT_TEST_PORT", "18083")),
            create_app(runtime, project / "frontend/dist"), threaded=True)
        def interrupt(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupt)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            runtime.stop()
