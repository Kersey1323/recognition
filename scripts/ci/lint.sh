#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv-ci
. .venv-ci/bin/activate
python -m pip install --upgrade pip uv
uv sync --frozen --active --group dev

ruff check \
  csrcqsf/__main__.py \
  csrcqsf/core/app.py \
  csrcqsf/core/settings.py \
  tests/test_docker_deployment_config.py \
  tests/test_k8s_runtime_contract.py \
  tests/test_gitops_metadata_scripts.py
