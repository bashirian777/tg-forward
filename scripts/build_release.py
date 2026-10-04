"""Build the frontend and include its dist in the Python distribution."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true", help="Use existing frontend dependencies")
    parser.add_argument("--frontend-only", action="store_true", help="Build and stage assets without making Python packages")
    args = parser.parse_args()
    if not args.skip_install:
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=ROOT / "frontend", check=True)
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True)
    target = ROOT / "src/tg_forwarder/web/dist"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "frontend/dist", target)
    if not args.frontend_only:
        subprocess.run([sys.executable, "-m", "build"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
