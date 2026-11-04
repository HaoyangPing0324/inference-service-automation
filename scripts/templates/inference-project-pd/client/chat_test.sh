#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
# shellcheck source=/dev/null
source "$CONFIG"

curl --fail --show-error "http://127.0.0.1:${SERVICE_PORT}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${SERVED_MODEL_NAME}\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}"
