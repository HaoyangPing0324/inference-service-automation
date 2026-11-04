#!/usr/bin/env bash
set -euo pipefail
# Linux container entry; ordinary benchmark_test.sh remains independent.
source "${EXPERIMENT_ENV:-/experiment.env}"
PROFILE_PROTOCOL=${PROFILE_PROTOCOL:-time}
MODE=${1:-}
[[ "$MODE" == torch || "$MODE" == nsys ]] || exit 2
[[ "$FRAMEWORK" == sglang ]] || { echo 'Profiling controller requires verified SGLang support' >&2; exit 2; }
ACTION=${2:-}
case "$ACTION" in
  --run) C=${3:-} ;;
  ''|--background) read -r -p 'C（最大并发请求数）：' C ;;
  *) exit 2 ;;
esac
[[ "$C" =~ ^[1-9][0-9]{0,8}$ ]] || { echo 'C must be a positive integer' >&2; exit 2; }
PROFILE_ROOT=${PROFILE_RUN_DIR:-/server/profiles/${MODE}-$(date +%Y%m%d-%H%M%S)-$$}
if [[ -e "$PROFILE_ROOT/workload.json" || -e "$PROFILE_ROOT/job.exitcode" ]]; then
  echo 'Run already contains workload/exit status; select a new isolated run' >&2; exit 2
fi
mkdir -p "$PROFILE_ROOT"
if [[ "$ACTION" == --background ]]; then
  SCRIPT_PATH=$(readlink -f -- "${BASH_SOURCE[0]}")
  nohup env PROFILE_RUN_DIR="$PROFILE_ROOT" bash "$SCRIPT_PATH" "$MODE" --run "$C" \
    > "$PROFILE_ROOT/job.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$PROFILE_ROOT/job.pid"
  printf 'Background PID=%s\nRun=%s\n' "$(< "$PROFILE_ROOT/job.pid")" "$PROFILE_ROOT"
  exit 0
fi
trap 'STATUS=$?; printf "%s\n" "$STATUS" > "$PROFILE_ROOT/job.exitcode"' EXIT
RUN_ARGS=(
  --mode "$MODE" --concurrency "$C"
  --base-url "http://127.0.0.1:$SERVICE_PORT"
  --model-path "$MODEL_PATH" --model "$SERVED_MODEL_NAME"
  --dataset-path "$DATASET_PATH" --isl "$ISL" --osl "$OSL"
  --seed "$((SEED_BASE + ISL + C))" --output-dir "$PROFILE_ROOT"
  --prefix "$PROFILE_PREFIX"
)
PROFILE_DRIVER=/client/run_time_profile.py
if [[ "$PROFILE_PROTOCOL" == time ]]; then
  [[ "$PREFIX_CACHE_MODE" == disabled ]] || { echo 'Time workload reuses a local prompt pool; disable prefix cache or explicitly adapt the workload' >&2; exit 2; }
  [[ "${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}" == 0 && "${PROFILE_HOOK_ENABLED:-0}" == 0 ]] || { echo 'Time profiling must not load the legacy stage adapter' >&2; exit 2; }
  RUN_ARGS+=(--prerun-seconds "$PROFILE_PRERUN_SECONDS" --capture-seconds "$PROFILE_CAPTURE_SECONDS" --max-requests "$PROFILE_MAX_REQUESTS" --prerun-completed-multiplier "$PROFILE_PRERUN_COMPLETED_MULTIPLIER" --postrun-completed-multiplier "$PROFILE_POSTRUN_COMPLETED_MULTIPLIER")
elif [[ "$PROFILE_PROTOCOL" == steps ]]; then
  PROFILE_DRIVER=/client/profile_windows.py
  RUN_ARGS+=(--protocol steps --prefill-steps "$PROFILE_PREFILL_STEPS" --decode-steps "$PROFILE_DECODE_STEPS")
else
  echo 'PROFILE_PROTOCOL must be time or steps' >&2; exit 2
fi
if [[ "${PROFILE_PD_SEPARATED:-0}" == 1 ]]; then
  for url in "${PROFILE_PREFILL_URLS[@]}"; do RUN_ARGS+=(--prefill-url "$url"); done
  for url in "${PROFILE_DECODE_URLS[@]}"; do RUN_ARGS+=(--decode-url "$url"); done
elif [[ "${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}" == 1 ]]; then
  RUN_ARGS+=(--single-stage-adapter)
fi
printf '%q ' python3 "$PROFILE_DRIVER" "${RUN_ARGS[@]}"
printf '\n'
HEALTH_URLS=("http://127.0.0.1:$SERVICE_PORT$HEALTH_PATH")
if [[ "${PROFILE_PD_SEPARATED:-0}" == 1 ]]; then
  for url in "${PROFILE_PREFILL_URLS[@]}" "${PROFILE_DECODE_URLS[@]}"; do
    HEALTH_URLS+=("${url%/}$HEALTH_PATH")
  done
fi
deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
for url in "${HEALTH_URLS[@]}"; do
  echo "Waiting for service readiness: $url"
  until curl --fail --silent --max-time 5 "$url" >/dev/null; do
    (( SECONDS < deadline )) || { echo "Service readiness timed out: $url" >&2; exit 1; }
    sleep 10
  done
done
python3 "$PROFILE_DRIVER" "${RUN_ARGS[@]}"
