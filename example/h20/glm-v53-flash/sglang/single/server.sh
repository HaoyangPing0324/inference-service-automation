#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
source "$ROOT/experiment.env"

(( ${#CONTAINER_CLI[@]} > 0 )) || { echo "CONTAINER_CLI is empty" >&2; exit 2; }
(( ${#SERVER_CONTAINER_ARGS[@]} > 0 )) || { echo "SERVER_CONTAINER_ARGS is empty" >&2; exit 2; }

# Execute on the confirmed Linux container host. Default interactive mode is unchanged.
MODE=${1:-shell}
case "$MODE" in shell|nsys) ;; *) echo 'Usage: server.sh [shell|nsys]' >&2; exit 2 ;; esac
RUN_ARGS=("${SERVER_CONTAINER_ARGS[@]}")
SOURCE_OVERRIDE_ARGS=()
if [[ "${SOURCE_OVERRIDE_MODE:-baseline}" != baseline ]]; then
  source "$ROOT/server/source_overrides/load.sh"
  source_override_load "$ROOT" server
  [[ "${RUN_ARGS[0]}" == run ]] || { echo 'Source replacements require a run command' >&2; exit 2; }
  RUN_ARGS=(run "${SOURCE_OVERRIDE_ARGS[@]}" "${RUN_ARGS[@]:1}")
fi
if [[ "$MODE" == nsys ]]; then
  [[ "${RUN_ARGS[0]}" == run ]] || {
    echo 'Nsys setup requires SERVER_CONTAINER_ARGS to start with run.' >&2; exit 2;
  }
  # Linux sysfs is exposed read-only; never use privileged mode as a substitute.
  RUN_ARGS=(run --mount type=bind,src=/sys,dst=/sys,readonly "${RUN_ARGS[@]:1}")
fi
"${CONTAINER_CLI[@]}" "${RUN_ARGS[@]}"
"${CONTAINER_CLI[@]}" exec -it "$SERVER_CONTAINER_NAME" bash
