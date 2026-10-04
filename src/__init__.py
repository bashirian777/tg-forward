"""Compatibility for the former ``python -m src.main`` checkout entry point."""
import sys
from pathlib import Path

_source_dir = str(Path(__file__).resolve().parent)
if _source_dir not in sys.path:
    sys.path.insert(0, _source_dir)
