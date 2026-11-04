#!/usr/bin/env bash
# Run only on the confirmed Linux container host, after scope/restart approval.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MODE=${1:-}
case "$MODE" in baseline|framework|operator|combined) ;; *)
  echo 'Usage: run_source_variant.sh baseline|framework|operator|combined <server.sh arguments>' >&2
  exit 2 ;;
esac
shift
export SOURCE_OVERRIDE_MODE="$MODE"
exec bash "$ROOT/server.sh" "$@"

