#!/usr/bin/env bash
# Capture callback order is verified against workload events and report evidence.
set -euo pipefail
: "${NSYS_REPORT_INDEX:?Missing capture index}"
: "${NSYS_REPORT_PATH:?Missing report path from Nsys}"
printf '%s\t%s\n' "$(date +%s.%N)" "$NSYS_REPORT_PATH" >> "$NSYS_REPORT_INDEX"
