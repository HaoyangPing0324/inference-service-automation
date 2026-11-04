#!/usr/bin/env bash
set -euo pipefail

if (( $# < 1 || $# > 2 )) || [[ "$1" != torch && "$1" != nsys ]] || [[ "${2:-}" != "" && "${2:-}" != --background ]]; then
  echo "Usage: bash /client/profile_capture.sh torch|nsys [--background]" >&2
  exit 2
fi

exec bash /client/profile_workload.sh "$@"
