#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
source "$ROOT/experiment.env"

(( ${#CONTAINER_CLI[@]} > 0 )) || { echo "CONTAINER_CLI is empty" >&2; exit 2; }
(( ${#CLIENT_CONTAINER_ARGS[@]} > 0 )) || { echo "CLIENT_CONTAINER_ARGS is empty" >&2; exit 2; }

if "${CONTAINER_CLI[@]}" inspect "$CLIENT_CONTAINER_NAME" >/dev/null 2>&1; then
  if [[ "$("${CONTAINER_CLI[@]}" inspect -f '{{.State.Running}}' "$CLIENT_CONTAINER_NAME")" == true ]]; then
    "${CONTAINER_CLI[@]}" stop --time 10 "$CLIENT_CONTAINER_NAME"
  fi
  "${CONTAINER_CLI[@]}" rm "$CLIENT_CONTAINER_NAME"
fi

"${CONTAINER_CLI[@]}" run -d --name "$CLIENT_CONTAINER_NAME" \
  "${CLIENT_CONTAINER_ARGS[@]}" \
  -v "$HOST_MODELS_DIR:$CONTAINER_MODELS_DIR:ro" \
  -v "$ROOT/server:/server" \
  -v "$ROOT/client:/client" \
  -v "$ROOT/experiment.env:/experiment.env:ro" \
  -w /client \
  "$IMAGE" sleep infinity

echo "Started client container: $CLIENT_CONTAINER_NAME"
