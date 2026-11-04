#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
[[ -r "$CONFIG" ]] || { echo "Missing experiment config: $CONFIG" >&2; exit 2; }
# shellcheck source=/dev/null
source "$CONFIG"

# Reapply the approved mode after config sourcing resets the hook-off default.
if [[ "${PROFILE_SINGLE_STAGE_RUNTIME_ENABLED:-0}" == 1 ]]; then
  [[ "${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}" == 1 && "${PROFILE_ROLE:-}" == single ]] || {
    echo 'Single-stage capture runtime was not approved for this role' >&2
    exit 2
  }
  export PROFILE_HOOK_ENABLED=1
fi

(( ${#SERVICE_CMD[@]} > 0 )) || { echo "SERVICE_CMD is empty" >&2; exit 2; }
(( ${#SERVICE_ARGS[@]} > 0 )) || { echo "SERVICE_ARGS is empty" >&2; exit 2; }

ARGS=("${SERVICE_ARGS[@]}")
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

exec "${SERVICE_CMD[@]}" "${ARGS[@]}"
