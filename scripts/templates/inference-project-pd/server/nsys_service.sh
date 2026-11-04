#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
# shellcheck source=/dev/null
source "$CONFIG"

ROLE=${1:-}
case "$ROLE" in
  prefill) ROLE_PORT=$PREFILL_PORT ;;
  decode) ROLE_PORT=$DECODE_PORT ;;
  *) echo "Usage: $0 {prefill|decode}" >&2; exit 2 ;;
esac

command -v "$NSYS_BIN" >/dev/null || {
  echo "nsys is unavailable inside this container; see the profiling document." >&2
  exit 1
}
bash "$(dirname -- "${BASH_SOURCE[0]}")/nsys_preflight.sh"
if curl --fail --silent --max-time 5 "http://127.0.0.1:${ROLE_PORT}${HEALTH_PATH}" >/dev/null; then
  echo "A server is already healthy on port ${ROLE_PORT}. Stop only this experiment's tracked server first." >&2
  exit 1
fi
RUN_ID=${NSYS_RUN_ID:-nsys-$(date +%Y%m%d-%H%M%S)-$$}
[[ "$RUN_ID" =~ ^[A-Za-z0-9_-]+$ ]] || { echo 'Invalid NSYS_RUN_ID' >&2; exit 2; }
RUN_DIR="/server/profiles/${RUN_ID}/${ROLE}"
mkdir -p "$RUN_DIR"
export NSYS_REPORT_INDEX="$RUN_DIR/report-index.tsv"
echo "Nsight Systems report: $RUN_DIR/${SERVED_MODEL_NAME}-${ROLE}.nsys-rep"
exec "$NSYS_BIN" profile "${NSYS_PROFILE_ARGS[@]}" \
  --after-report-ready='bash /server/nsys_report_ready.sh' \
  -o "$RUN_DIR/${SERVED_MODEL_NAME}-${ROLE}" bash /server/profile_service.sh "$ROLE"
