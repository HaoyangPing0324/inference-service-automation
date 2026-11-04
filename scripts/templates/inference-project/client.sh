#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
source "$ROOT/experiment.env"

(( ${#CONTAINER_CLI[@]} > 0 )) || { echo "CONTAINER_CLI is empty" >&2; exit 2; }
(( ${#CLIENT_CONTAINER_ARGS[@]} > 0 )) || { echo "CLIENT_CONTAINER_ARGS is empty" >&2; exit 2; }

"${CONTAINER_CLI[@]}" "${CLIENT_CONTAINER_ARGS[@]}"
"${CONTAINER_CLI[@]}" exec -it "$CLIENT_CONTAINER_NAME" bash
