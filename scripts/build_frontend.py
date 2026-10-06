"""Build the frontend and stage its assets for the Python server."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true", help="Use existing frontend dependencies")
    args = parser.parse_args()
    if not args.skip_install:
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=ROOT / "frontend", check=True)
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True)
    target = ROOT / "src/tg_forwarder/web/dist"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "frontend/dist", target)


if __name__ == "__main__":
    main()
