#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
# shellcheck source=/dev/null
source "$CONFIG"
if [[ "${PROFILE_PROTOCOL:-time}" == time && ( "${PROFILE_HOOK_ENABLED:-0}" != 0 || "${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}" != 0 ) ]]; then
  echo "Time capture requires native mixed profiling without a stage hook" >&2; exit 2
fi

case "${1:-no-key-averages}" in
  key-averages) PROFILE_KEY_AVERAGES_ENABLED=1 ;;
  no-key-averages) PROFILE_KEY_AVERAGES_ENABLED=0 ;;
  *) echo "Profiler aggregation must be key-averages or no-key-averages" >&2; exit 2 ;;
esac

export PROFILE_HOOK_ENABLED PROFILE_MANAGER_MODULE PROFILE_HOOK_MODULE PROFILE_PREFIX PROFILE_PREFILL_SCOPE PROFILE_PREFILL_STEPS PROFILE_DECODE_STEPS PROFILE_KEY_AVERAGES_ENABLED
for assignment in "${PROFILE_FRAMEWORK_ENV[@]}"; do
  export "$assignment"
done
if [[ "${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}" == 1 ]]; then
  export PROFILE_HOOK_ENABLED=1 PROFILE_ROLE=single
  export PROFILE_SINGLE_STAGE_RUNTIME_ENABLED=1
  export PYTHONPATH="/server/profiling_hooks${PYTHONPATH:+:$PYTHONPATH}"
elif [[ "$PROFILE_HOOK_ENABLED" == 1 ]]; then
  echo "Single-stage adapter requires PROFILE_SINGLE_STAGE_ADAPTER_APPROVED=1" >&2
  exit 2
fi
[[ "$PROFILE_KEY_AVERAGES_ENABLED" == 0 ]] || { echo "Native key_averages needs a separately approved adapter" >&2; exit 2; }
exec bash /server/service.sh
