"""Tests dans un job de l'image courante, sans accès à la base de production."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="isbn-tests-") as deps:
    venv.create(deps, with_pip=True)
    python = str(Path(deps) / "bin" / "python")
    subprocess.run([python, "-m", "pip", "install", "--quiet",
                    "-r", str(root / "requirements-dev.txt")], cwd=root, check=True)
    env = dict(os.environ, PYTHONPATH=str(root / "src"),
               BOT_MODE="DRY_RUN", BOT_WRITE_ENABLED="false", BOT_COMMUNITY_APPROVED="false")
    result = subprocess.run([python, "-m", "pytest", "-q", str(root / "tests")], cwd=root, env=env)
    sys.exit(result.returncode)
