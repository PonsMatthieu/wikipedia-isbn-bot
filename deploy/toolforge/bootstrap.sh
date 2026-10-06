#!/usr/bin/env bash
# Alternative aux buildpacks : exécuter dans un job python3.13, pas sur le bastion.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
