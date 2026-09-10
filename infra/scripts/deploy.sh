#!/usr/bin/env bash

set -euo pipefail

INFRA="$(cd "$(dirname "$0")/.." && pwd)"
cd "$INFRA"

python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt

CONTEXT_ARGS=()
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  CONTEXT_ARGS+=(-c "deepseekApiKey=${DEEPSEEK_API_KEY}")
fi

cdk bootstrap "$@"
cdk deploy RagChatbotStack --require-approval never "${CONTEXT_ARGS[@]}" "$@"

echo ""
echo "Next: push Docker images and restart ECS"
echo "  ./scripts/deploy-images.sh"
