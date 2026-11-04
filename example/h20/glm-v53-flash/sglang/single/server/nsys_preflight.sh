#!/usr/bin/env bash
# Run inside the Linux collection container, before loading model weights.
set -euo pipefail
CPU_SYSFS=${1:-/sys/devices/system/cpu}
for name in online possible present; do
  file="$CPU_SYSFS/$name"
  value=''
  if [[ ! -r "$file" ]] || ! value=$(cat -- "$file") || [[ -z "$value" ]]; then
    echo "Nsys preflight failed: CPU topology file is unreadable or empty: $file" >&2
    echo 'Ask approval to recreate only this experiment container with read-only Linux sysfs; do not restart unrelated services or install tools.' >&2
    exit 2
  fi
done
echo 'Nsys preflight: CPU topology is readable (capture/report health still requires validation).'
