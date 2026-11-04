#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
[[ -r "$CONFIG" ]] || { echo "Missing experiment config: $CONFIG" >&2; exit 2; }
# shellcheck source=/dev/null
source "$CONFIG"

ROLE=${1:-}
if [[ "$ROLE" == router ]]; then
  (( ${#ROUTER_CMD[@]} > 0 )) || { echo "ROUTER_CMD is empty" >&2; exit 2; }
  exec "${ROUTER_CMD[@]}" "${ROUTER_ARGS[@]}"
fi

case "$ROLE" in
  prefill)
    ROLE_PORT=$PREFILL_PORT
    ROLE_ARGS=("${PREFILL_SERVICE_ARGS[@]}")
    ;;
  decode)
    ROLE_PORT=$DECODE_PORT
    ROLE_ARGS=("${DECODE_SERVICE_ARGS[@]}")
    ;;
  *) echo "Usage: $0 {prefill|decode|router}" >&2; exit 2 ;;
esac

(( ${#SERVICE_CMD[@]} > 0 )) || { echo "SERVICE_CMD is empty" >&2; exit 2; }
(( ${#SERVICE_ARGS[@]} > 0 )) || { echo "SERVICE_ARGS is empty" >&2; exit 2; }

ARGS=("${SERVICE_ARGS[@]}" "${ROLE_ARGS[@]}")
case "$PREFIX_CACHE_MODE" in
  disabled)
    if (( ${#PREFIX_CACHE_DISABLE_ARGS[@]} == 0 )) && [[ "$PREFIX_CACHE_DEFAULT_DISABLED" != 1 ]]; then
      echo "No-prefix baseline is not verified: set disable args or DEFAULT_DISABLED=1." >&2
      exit 2
    fi
    ARGS+=("${PREFIX_CACHE_DISABLE_ARGS[@]}")
    ;;
  enabled)
    ARGS+=("${PREFIX_CACHE_ENABLE_ARGS[@]}")
    ;;
  *)
    echo "PREFIX_CACHE_MODE must be disabled or enabled" >&2
    exit 2
    ;;
esac

exec env "${SERVICE_ENV[@]}" "${SERVICE_CMD[@]}" "${ARGS[@]}" \
  --host "$SERVICE_HOST" \
  --port "$ROLE_PORT" \
  --disaggregation-mode "$ROLE" \
  --disaggregation-transfer-backend "$PD_TRANSFER_BACKEND" \
  --disaggregation-ib-device "$PD_IB_DEVICES"
