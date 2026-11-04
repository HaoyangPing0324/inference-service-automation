#!/usr/bin/env bash
set -euo pipefail
# Read-only command expansion on a Linux execution host; never starts Docker.
ROOT=$(cd -- "${1:?experiment directory required}" && pwd)
C=${2:?concurrency required}
RUN_DIR=${3:?container run directory required}
[[ "$C" =~ ^[1-9][0-9]*$ ]] || exit 2
export EXPERIMENT_ENV="$ROOT/experiment.env"
source "$EXPERIMENT_ENV"
print_command() { printf '%q ' "$@"; printf '\n'; }
export -f print_command

roles=(single)
[[ "${PROFILE_PD_SEPARATED:-0}" != 1 ]] || roles=(prefill decode router)
declare -A service_commands
for role in "${roles[@]}"; do
  printf '# service:%s\n' "$role"
  # Shadow only the shell exec builtin in this subprocess. Source the real
  # service script so argument order and prefix-cache branches stay identical.
  service_commands[$role]=$(
    exec() { print_command "$@"; exit 0; }
    export -f exec
    if [[ "$role" == single ]]; then
      bash "$ROOT/server/service.sh"
    else
      bash "$ROOT/server/service.sh" "$role"
    fi
  )
  printf '%s\n' "${service_commands[$role]}"
done
printf '# nsys callback source\n'
sed -n '1,$p' "$ROOT/server/nsys_report_ready.sh"
for role in "${roles[@]}"; do
  [[ "$role" != router ]] || continue
  folder="$RUN_DIR"
  suffix=''
  if [[ "$role" != single ]]; then folder+="/$role"; suffix="-$role"; fi
  printf '# nsys:%s (container environment)\n' "$role"
  printf '%q ' env "NSYS_REPORT_INDEX=$folder/report-index.tsv" \
    "$NSYS_BIN" profile "${NSYS_PROFILE_ARGS[@]}" \
    --after-report-ready='bash /server/nsys_report_ready.sh' \
    -o "$folder/$SERVED_MODEL_NAME$suffix" env \
    "PROFILE_HOOK_ENABLED=$PROFILE_HOOK_ENABLED" "${PROFILE_FRAMEWORK_ENV[@]}"
  printf '%s\n' "${service_commands[$role]}"
done
printf '# benchmark\n'
for c in "${CONCURRENCIES[@]}"; do
  args=("${BENCHMARK_BASE_ARGS[@]}")
  append() { [[ -z "$1" ]] || args+=("$1" "$2"); }
  append "$BENCHMARK_DATASET_PATH_FLAG" "$DATASET_PATH"
  append "$BENCHMARK_INPUT_LEN_FLAG" "$ISL"
  append "$BENCHMARK_OUTPUT_LEN_FLAG" "$OSL"
  append "$BENCHMARK_WARMUP_FLAG" "$WARMUP_REQUESTS"
  append "$BENCHMARK_NUM_PROMPTS_FLAG" "$((c * REQUEST_MULTIPLIER))"
  append "$BENCHMARK_CONCURRENCY_FLAG" "$c"
  append "$BENCHMARK_SEED_FLAG" "$((SEED_BASE + ISL + c))"
  append "$BENCHMARK_OUTPUT_FILE_FLAG" "/client/results/benchmark/input_${ISL}_output_${OSL}_concurrency${c}.jsonl"
  print_command "${BENCHMARK_CMD[@]}" "${args[@]}"
done
printf '# profiler\n'
args=(--mode torch --concurrency "$C" --base-url "http://127.0.0.1:$SERVICE_PORT"
  --model-path "$MODEL_PATH" --model "$SERVED_MODEL_NAME" --dataset-path "$DATASET_PATH"
  --isl "$ISL" --osl "$OSL" --seed "$((SEED_BASE + ISL + C))"
  --output-dir "$RUN_DIR"
  --prefix "$PROFILE_PREFIX")
PROFILE_DRIVER=/client/run_time_profile.py
if [[ "${PROFILE_PROTOCOL:-time}" == time ]]; then
  args+=(--prerun-seconds "$PROFILE_PRERUN_SECONDS" --capture-seconds "$PROFILE_CAPTURE_SECONDS"
    --max-requests "$PROFILE_MAX_REQUESTS"
    --prerun-completed-multiplier "$PROFILE_PRERUN_COMPLETED_MULTIPLIER"
    --postrun-completed-multiplier "$PROFILE_POSTRUN_COMPLETED_MULTIPLIER")
elif [[ "$PROFILE_PROTOCOL" == steps ]]; then
  PROFILE_DRIVER=/client/profile_windows.py
  args+=(--protocol steps --prefill-steps "$PROFILE_PREFILL_STEPS" --decode-steps "$PROFILE_DECODE_STEPS")
else
  echo 'Unknown profiling protocol' >&2; exit 2
fi
if [[ "${PROFILE_PD_SEPARATED:-0}" == 1 ]]; then
  for url in "${PROFILE_PREFILL_URLS[@]}"; do args+=(--prefill-url "$url"); done
  for url in "${PROFILE_DECODE_URLS[@]}"; do args+=(--decode-url "$url"); done
elif [[ "${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}" == 1 ]]; then
  args+=(--single-stage-adapter)
fi
print_command python3 "$PROFILE_DRIVER" "${args[@]}"
