#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
# shellcheck source=/dev/null
source "$CONFIG"
if [[ "${PROFILE_PROTOCOL:-time}" == time && ( "${PROFILE_HOOK_ENABLED:-0}" != 0 || "${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}" != 0 ) ]]; then
  echo "Time capture requires native mixed profiling without a stage hook" >&2; exit 2
fi

PROFILE_KEY_AVERAGES_ENABLED=${PROFILE_KEY_AVERAGES_ENABLED:-0}
case "$PROFILE_KEY_AVERAGES_ENABLED" in 0|1) ;; *) echo "PROFILE_KEY_AVERAGES_ENABLED must be 0 or 1" >&2; exit 2 ;; esac

ROLE=${1:-}
case "$ROLE" in prefill|decode) ;; *) echo "Usage: $0 {prefill|decode}" >&2; exit 2 ;; esac

export PROFILE_HOOK_ENABLED PROFILE_MANAGER_MODULE PROFILE_HOOK_MODULE PROFILE_PREFIX
export PROFILE_PREFILL_SCOPE PROFILE_PREFILL_STEPS PROFILE_DECODE_STEPS
export PROFILE_KEY_AVERAGES_ENABLED
export PROFILE_ROLE="$ROLE"
for assignment in "${PROFILE_FRAMEWORK_ENV[@]}"; do
  export "$assignment"
done
if [[ "$PROFILE_HOOK_ENABLED" == 1 ]]; then
  echo "Native profiling requires PROFILE_HOOK_ENABLED=0; adapter needs explicit approval" >&2
  exit 2
fi
[[ "$PROFILE_KEY_AVERAGES_ENABLED" == 0 ]] || { echo "Native key_averages needs a separately approved adapter" >&2; exit 2; }
exec bash /server/service.sh "$ROLE"
