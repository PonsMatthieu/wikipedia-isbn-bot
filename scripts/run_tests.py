"""Tests dans un job de l'image courante, sans accès à la base de production."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="isbn-tests-") as deps:
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--target", deps, "pytest>=8,<10"], check=True)
    env = dict(os.environ, PYTHONPATH=str(root / "src") + os.pathsep + deps,
               BOT_MODE="DRY_RUN", BOT_WRITE_ENABLED="false", BOT_COMMUNITY_APPROVED="false")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(root / "tests")], cwd=root, env=env)
    sys.exit(result.returncode)
