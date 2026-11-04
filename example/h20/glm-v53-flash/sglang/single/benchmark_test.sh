#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
source "$ROOT/experiment.env"

BENCHMARK_MODE=${1:-full}
[[ $# -le 1 && ( "$BENCHMARK_MODE" == full || "$BENCHMARK_MODE" == tuning ) ]] || {
  echo "Usage: benchmark_test.sh [full|tuning]" >&2
  exit 2
}

[[ "$BENCHMARK_MODE" != full || "$PREFIX_CACHE_MODE" == disabled ]] || {
  echo "The first benchmark must use PREFIX_CACHE_MODE=disabled." >&2
  exit 2
}
"${CONTAINER_CLI[@]}" inspect "$CLIENT_CONTAINER_NAME" >/dev/null 2>&1 || {
  echo "Client container does not exist: $CLIENT_CONTAINER_NAME" >&2
  exit 1
}
[[ "$("${CONTAINER_CLI[@]}" inspect -f '{{.State.Running}}' "$CLIENT_CONTAINER_NAME")" == true ]] || {
  echo "Client container is not running: $CLIENT_CONTAINER_NAME" >&2
  exit 1
}

"${CONTAINER_CLI[@]}" exec -i "$CLIENT_CONTAINER_NAME" bash -s -- "$BENCHMARK_MODE" <<'REMOTE_SCRIPT'
set -euo pipefail
# shellcheck source=/dev/null
source /experiment.env
BENCHMARK_MODE=$1
if [[ "$BENCHMARK_MODE" == tuning ]]; then
  RUN_CONCURRENCIES=(1 8 32)
else
  RUN_CONCURRENCIES=("${CONCURRENCIES[@]}")
fi
printf 'Benchmark mode=%s concurrency=%s\n' "$BENCHMARK_MODE" "${RUN_CONCURRENCIES[*]}"

(( ${#BENCHMARK_CMD[@]} > 0 )) || { echo "BENCHMARK_CMD is empty" >&2; exit 2; }
(( ${#BENCHMARK_BASE_ARGS[@]} > 0 )) || { echo "BENCHMARK_BASE_ARGS is empty" >&2; exit 2; }
[[ -n "$SERVICE_PORT" ]] || { echo "SERVICE_PORT is empty" >&2; exit 2; }
if [[ -n "$DATASET_PATH" && ! -s "$DATASET_PATH" ]]; then
  echo "Dataset not found: $DATASET_PATH" >&2
  exit 1
fi

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
until curl --fail --silent --show-error "http://127.0.0.1:${SERVICE_PORT}${HEALTH_PATH}" >/dev/null; do
  (( SECONDS < deadline )) || { echo "Service health check timed out" >&2; exit 1; }
  sleep 2
done

RESULT_DIR="/client/results/${RESULT_NAME_PREFIX}_bench_${BENCHMARK_MODE}_input_${ISL}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESULT_DIR"

append_value() {
  local flag=$1 value=$2
  [[ -z "$flag" ]] || RUN_ARGS+=("$flag" "$value")
}

for C in "${RUN_CONCURRENCIES[@]}"; do
  N=$((C * REQUEST_MULTIPLIER))
  SEED=$((SEED_BASE + ISL + C))
  LOG_FILE="$RESULT_DIR/input_${ISL}_output_${OSL}_concurrency${C}.log"
  RESULT_FILE="$RESULT_DIR/input_${ISL}_output_${OSL}_concurrency${C}.jsonl"
  RUN_ARGS=("${BENCHMARK_BASE_ARGS[@]}")
  append_value "$BENCHMARK_DATASET_PATH_FLAG" "$DATASET_PATH"
  append_value "$BENCHMARK_INPUT_LEN_FLAG" "$ISL"
  append_value "$BENCHMARK_OUTPUT_LEN_FLAG" "$OSL"
  append_value "$BENCHMARK_WARMUP_FLAG" "$WARMUP_REQUESTS"
  append_value "$BENCHMARK_NUM_PROMPTS_FLAG" "$N"
  append_value "$BENCHMARK_CONCURRENCY_FLAG" "$C"
  append_value "$BENCHMARK_SEED_FLAG" "$SEED"
  append_value "$BENCHMARK_OUTPUT_FILE_FLAG" "$RESULT_FILE"
  "${BENCHMARK_CMD[@]}" "${RUN_ARGS[@]}" 2>&1 | tee "$LOG_FILE"
  echo "Concurrency $C completed."
done

python3 /client/parse_bench_result.py "$RESULT_DIR" --device-count "$DEVICE_COUNT"
echo "Results: $RESULT_DIR"
REMOTE_SCRIPT
