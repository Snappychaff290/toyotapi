#!/usr/bin/env bash
# FieldRig Phase 1 / step 4: Python venv + FieldRig install with Pi extras.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.local/share/fieldrig/venv"

echo "==> Creating venv at ${VENV}"
mkdir -p "$(dirname "$VENV")"
python -m venv "$VENV"

echo "==> Installing FieldRig (+ Pi hardware extras)"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -e "${REPO_DIR}[pi]"

echo "==> Smoke check"
"$VENV/bin/python" -m fieldrig --check || true

echo "==> Done. Next: ./05-autostart.sh"
