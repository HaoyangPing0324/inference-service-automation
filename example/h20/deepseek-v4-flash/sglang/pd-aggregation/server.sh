#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
source "$ROOT/experiment.env"

(( ${#CONTAINER_CLI[@]} > 0 )) || { echo "CONTAINER_CLI is empty" >&2; exit 2; }
(( ${#SERVER_CONTAINER_ARGS[@]} > 0 )) || { echo "SERVER_CONTAINER_ARGS is empty" >&2; exit 2; }

MODE=${1:-}
ENTRYPOINT=()
PROFILE_KEY_AVERAGES_ENABLED=0
case "$MODE" in
  prefill)
    ROLE=prefill
    CONTAINER_NAME=$PREFILL_CONTAINER_NAME
    GPU_IDS=$PREFILL_GPU_IDS
    ENTRYPOINT=(bash /server/service.sh "$ROLE")
    ;;
  decode)
    ROLE=decode
    CONTAINER_NAME=$DECODE_CONTAINER_NAME
    GPU_IDS=$DECODE_GPU_IDS
    ENTRYPOINT=(bash /server/service.sh "$ROLE")
    ;;
  profile-prefill)
    ROLE=prefill
    CONTAINER_NAME=$PREFILL_CONTAINER_NAME
    GPU_IDS=$PREFILL_GPU_IDS
    ENTRYPOINT=(bash /server/profile_service.sh "$ROLE")
    case "${2:-no-key-averages}" in key-averages) PROFILE_KEY_AVERAGES_ENABLED=1 ;; no-key-averages) ;; *) echo "Profiler aggregation must be key-averages or no-key-averages" >&2; exit 2 ;; esac
    ;;
  profile-decode)
    ROLE=decode
    CONTAINER_NAME=$DECODE_CONTAINER_NAME
    GPU_IDS=$DECODE_GPU_IDS
    ENTRYPOINT=(bash /server/profile_service.sh "$ROLE")
    case "${2:-no-key-averages}" in key-averages) PROFILE_KEY_AVERAGES_ENABLED=1 ;; no-key-averages) ;; *) echo "Profiler aggregation must be key-averages or no-key-averages" >&2; exit 2 ;; esac
    ;;
  nsys-prefill)
    ROLE=prefill
    CONTAINER_NAME=$PREFILL_CONTAINER_NAME
    GPU_IDS=$PREFILL_GPU_IDS
    ENTRYPOINT=(bash /server/nsys_service.sh "$ROLE")
    ;;
  nsys-decode)
    ROLE=decode
    CONTAINER_NAME=$DECODE_CONTAINER_NAME
    GPU_IDS=$DECODE_GPU_IDS
    ENTRYPOINT=(bash /server/nsys_service.sh "$ROLE")
    ;;
  router)
    ROLE=router
    CONTAINER_NAME=$ROUTER_CONTAINER_NAME
    GPU_IDS=''
    ENTRYPOINT=(bash /server/service.sh router)
    ;;
  *)
    echo "Usage: $0 {prefill|decode|profile-prefill|profile-decode|nsys-prefill|nsys-decode|router} [key-averages|no-key-averages]" >&2
    exit 2
    ;;
esac

SOURCE_OVERRIDE_ARGS=()
if [[ "${SOURCE_OVERRIDE_MODE:-baseline}" != baseline ]]; then
  source "$ROOT/server/source_overrides/load.sh"
  source_override_load "$ROOT" "$ROLE"
fi

if "${CONTAINER_CLI[@]}" inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  if [[ "$("${CONTAINER_CLI[@]}" inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" == true ]]; then
    "${CONTAINER_CLI[@]}" stop --time 10 "$CONTAINER_NAME"
  fi
  "${CONTAINER_CLI[@]}" rm "$CONTAINER_NAME"
fi

COMMON_MOUNTS=(
  -v "$HOST_MODELS_DIR:$CONTAINER_MODELS_DIR:ro"
  -v "$ROOT/server:/server"
  -v "$ROOT/client:/client"
  -v "$ROOT/experiment.env:/experiment.env:ro"
)

ROLE_MOUNTS=()
if [[ "$MODE" == nsys-prefill || "$MODE" == nsys-decode ]]; then
  # Linux collection containers need readable host CPU topology for the importer.
  ROLE_MOUNTS+=(--mount type=bind,src=/sys,dst=/sys,readonly)
fi
if [[ "$ROLE" == decode ]]; then
  mkdir -p "$ROOT/runtime_cache/sglang"
  ROLE_MOUNTS+=(
    -v "$ROOT/runtime_cache/sglang:/root/.cache/sglang"
  )
fi

if [[ "$ROLE" == router ]]; then
  "${CONTAINER_CLI[@]}" run -d --name "$CONTAINER_NAME" \
    --network host \
    "${SOURCE_OVERRIDE_ARGS[@]}" \
    "${COMMON_MOUNTS[@]}" \
    -w /server \
    "$IMAGE" "${ENTRYPOINT[@]}"
else
  "${CONTAINER_CLI[@]}" run -d --name "$CONTAINER_NAME" \
    "${SERVER_CONTAINER_ARGS[@]}" \
    "${SOURCE_OVERRIDE_ARGS[@]}" \
    -e "CUDA_VISIBLE_DEVICES=$GPU_IDS" \
    -e "PROFILE_KEY_AVERAGES_ENABLED=$PROFILE_KEY_AVERAGES_ENABLED" \
    -e "NSYS_RUN_ID=${NSYS_RUN_ID:-}" \
    "${COMMON_MOUNTS[@]}" \
    "${ROLE_MOUNTS[@]}" \
    -w /server \
    "$IMAGE" "${ENTRYPOINT[@]}"
fi

echo "Started $MODE container: $CONTAINER_NAME"
