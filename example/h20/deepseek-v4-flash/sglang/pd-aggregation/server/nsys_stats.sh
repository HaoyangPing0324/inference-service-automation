#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
# shellcheck source=/dev/null
source "$CONFIG"
ACTION=${1:-}
case "$ACTION" in
  ''|--background) ;;
  --run) [[ $# == 2 && -f "$2" && "$2" == *.nsys-rep ]] || exit 2 ;;
  *) echo "Usage: bash /server/nsys_stats.sh [--background]" >&2; exit 2 ;;
esac

PROFILE_ROOT=${PROFILE_ROOT:-/server/profiles}
command -v "$NSYS_BIN" >/dev/null || { echo "找不到 nsys，请在 server 容器内执行。" >&2; exit 1; }
[[ -d "$PROFILE_ROOT" ]] || { echo "报告目录不存在：$PROFILE_ROOT" >&2; exit 1; }

if [[ "$ACTION" == --run ]]; then
  REPORT=$2
else
  mapfile -d '' -t REPORTS < <(find "$PROFILE_ROOT" -type f -name '*.nsys-rep' -print0 | sort -z)
  (( ${#REPORTS[@]} > 0 )) || { echo "没有找到 .nsys-rep 报告：$PROFILE_ROOT" >&2; exit 1; }
  echo "请选择要统计的 NSYS 报告："
  PS3="输入编号："
  select REPORT in "${REPORTS[@]}" "取消"; do
    [[ "$REPORT" == 取消 ]] && exit 0
    [[ -n "$REPORT" ]] && break
    echo "编号无效，请重新选择。" >&2
  done
fi

PREFIX=${REPORT%.nsys-rep}
CSV="$PREFIX.stats.csv"
STDERR="$PREFIX.stats.stderr"
if [[ "$ACTION" != --run && ( -e "$CSV" || -e "$STDERR" ) ]]; then
  read -r -p "该报告已有统计文件，重新生成并覆盖？[y/N] " ANSWER || exit 0
  [[ "$ANSWER" == y || "$ANSWER" == Y ]] || exit 0
fi
if [[ "$ACTION" == --background ]]; then
  SCRIPT_PATH=$(readlink -f -- "${BASH_SOURCE[0]}")
  nohup bash "$SCRIPT_PATH" --run "$REPORT" > "$PREFIX.stats.job.log" 2>&1 < /dev/null &
  JOB_PID=$!
  printf '%s\n' "$JOB_PID" > "$PREFIX.stats.pid"
  printf '后台统计已启动，PID=%s\n日志：%s.stats.job.log\n完成状态：%s.stats.exitcode（0为成功）\n' \
    "$JOB_PID" "$PREFIX" "$PREFIX"
  exit 0
fi
trap 'STATUS=$?; printf "%s\n" "$STATUS" > "$PREFIX.stats.exitcode"' EXIT

if "$NSYS_BIN" stats --report cuda_gpu_kern_sum,cuda_api_sum --format csv "$REPORT" > "$CSV" 2> "$STDERR"; then
  printf '统计完成：\n  %s\n  %s\n' "$CSV" "$STDERR"
  [[ ! -f "$PREFIX.sqlite" ]] || printf '数据库：\n  %s\n' "$PREFIX.sqlite"
else
  echo "统计失败，请查看：$STDERR" >&2
  exit 1
fi
