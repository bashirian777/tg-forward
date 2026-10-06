"""Run the application directly from a source checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tg_forwarder.cli import run

if __name__ == "__main__":
    run()
