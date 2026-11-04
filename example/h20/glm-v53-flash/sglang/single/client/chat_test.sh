#!/usr/bin/env bash
set -euo pipefail
source "${EXPERIMENT_ENV:-/experiment.env}"
exec python3 /client/chat_test.py "$SERVICE_PORT" "$SERVED_MODEL_NAME"
