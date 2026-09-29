#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python -m ruff format --check core tests
python -m ruff check core tests
python -m mypy
python -m pytest
jarvis check
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
