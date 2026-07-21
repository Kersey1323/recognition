#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv-ci
. .venv-ci/bin/activate
python -m pip install --upgrade pip uv
uv sync --frozen --active --group dev

python -m build

