#!/usr/bin/env bash
# Sourced only by a Linux container-host launcher. No lifecycle operations here.
set -euo pipefail

source_override_load() {
  local root=$1 role=$2 mode=${SOURCE_OVERRIDE_MODE:-baseline}
  SOURCE_OVERRIDE_ARGS=()
  case "$mode" in baseline) return 0 ;; framework|operator|combined) ;; *)
    echo "Unknown SOURCE_OVERRIDE_MODE: $mode" >&2; return 2 ;;
  esac
  local base="$root/server/source_overrides" selected=0 item group i src dst resolved
  [[ -r "$base/manifest.env" ]] || { echo 'Missing source override manifest' >&2; return 2; }
  source "$base/manifest.env"
  (( ${#OVERRIDE_ROLES[@]} > 0 )) || { echo 'Confirm OVERRIDE_ROLES before enabling replacements' >&2; return 2; }
  for item in "${OVERRIDE_ROLES[@]}"; do [[ "$item" != "$role" ]] || selected=1; done
  (( selected == 1 )) || return 0
  command -v realpath >/dev/null || { echo 'realpath is required for source override validation; ask before installing tools' >&2; return 2; }
  base=$(realpath -- "$base")
  local -a sources=() targets=() paths=() gs=() gt=() gp=()
  local -A seen=()
  for group in framework operator; do
    [[ "$mode" == combined || "$mode" == "$group" ]] || continue
    if [[ "$group" == framework ]]; then
      gs=("${OVERRIDE_FRAMEWORK_SOURCES[@]}"); gt=("${OVERRIDE_FRAMEWORK_TARGETS[@]}")
      gp=("${OVERRIDE_FRAMEWORK_PYTHONPATH[@]}")
    else
      gs=("${OVERRIDE_OPERATOR_SOURCES[@]}"); gt=("${OVERRIDE_OPERATOR_TARGETS[@]}")
      gp=("${OVERRIDE_OPERATOR_PYTHONPATH[@]}")
    fi
    (( ${#gs[@]} > 0 && ${#gs[@]} == ${#gt[@]} )) || {
      echo "Missing or mismatched source/target entries: $group" >&2; return 2;
    }
    sources+=("${gs[@]}"); targets+=("${gt[@]}"); paths+=("${gp[@]}")
  done
  for ((i=0; i<${#sources[@]}; i++)); do
    src=${sources[i]}; dst=${targets[i]}
    [[ -n "$src" && "$src" != /* && "$src" != *:* && "$src" != *$'\n'* && "$src" != *,* ]] || {
      echo "Source must be a relative, unambiguous path: $src" >&2; return 2;
    }
    resolved=$(realpath -e -- "$base/$src") || return 2
    [[ "$resolved" == "$base/"* && -f "$resolved" && -r "$resolved" && "$resolved" != *,* ]] || {
      echo "Source is not a readable file inside source_overrides: $src" >&2; return 2;
    }
    [[ "$dst" == /* && "$dst" != / && "$dst" != */ && "$dst" != *:* && "$dst" != *,* && "$dst" != *$'\n'* && "$dst" != *//* && "$dst" != */../* && "$dst" != */./* && "$dst" != */.. && "$dst" != */. ]] || {
      echo "Invalid container file target: $dst" >&2; return 2;
    }
    [[ -z ${seen[$dst]+present} ]] || { echo "Conflicting replacement target: $dst" >&2; return 2; }
    seen[$dst]=1
    SOURCE_OVERRIDE_ARGS+=(--mount "type=bind,src=$resolved,dst=$dst,readonly")
  done
  local pythonpath='' entry
  for item in "${paths[@]}"; do
    [[ -n "$item" && "$item" != /* && "$item" != *:* && "$item" != *,* && "$item" != *$'\n'* && "$item" != *\\* ]] || {
      echo "PYTHONPATH entry must be a relative directory: $item" >&2; return 2;
    }
    resolved=$(realpath -e -- "$base/$item") || return 2
    [[ "$resolved" == "$base/"* && -d "$resolved" ]] || { echo "PYTHONPATH escapes source_overrides: $item" >&2; return 2; }
    entry="/server/source_overrides/${resolved#"$base/"}"
    pythonpath="${pythonpath:+$pythonpath:}$entry"
  done
  if [[ -n "$pythonpath" ]]; then
    [[ "${OVERRIDE_BASE_PYTHONPATH_CONFIRMED:-0}" == 1 ]] || {
      echo 'Confirm the image PYTHONPATH before adding module search directories' >&2; return 2;
    }
    pythonpath="${pythonpath}${OVERRIDE_BASE_PYTHONPATH:+:$OVERRIDE_BASE_PYTHONPATH}"
    SOURCE_OVERRIDE_ARGS+=(-e "PYTHONPATH=$pythonpath")
  fi
}
