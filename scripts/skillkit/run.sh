#!/usr/bin/env bash
# Run every skillkit scan into one output directory (bash 3.2 compatible).
# Usage: run.sh --project <dir> --out <dir> [--since <days>] [--claude-home <dir>] [--plugin-list <json>] [--extra <dir>]...
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT=""; OUT=""; SINCE=30
HOME_ARGS=(); PL_ARGS=(); EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --since) SINCE="$2"; shift 2 ;;
    --claude-home) HOME_ARGS=(--claude-home "$2"); shift 2 ;;
    --plugin-list) PL_ARGS=(--plugin-list "$2"); shift 2 ;;
    --extra) EXTRA+=(--extra "$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$PROJECT" ] || [ -z "$OUT" ]; then
  echo "usage: run.sh --project <dir> --out <dir> [--since N] [--claude-home DIR] [--plugin-list FILE] [--extra DIR]" >&2
  exit 2
fi
mkdir -p "$OUT"
python3 -I "$HERE/inventory.py" --project "$PROJECT" --out "$OUT/inventory.json" \
  ${HOME_ARGS[@]+"${HOME_ARGS[@]}"} ${PL_ARGS[@]+"${PL_ARGS[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}
python3 -I "$HERE/usage.py" --since "$SINCE" --out "$OUT/usage.json" ${HOME_ARGS[@]+"${HOME_ARGS[@]}"}
python3 -I "$HERE/hooks_mcp.py" --project "$PROJECT" --out "$OUT/hooks_mcp.json" \
  ${HOME_ARGS[@]+"${HOME_ARGS[@]}"} ${PL_ARGS[@]+"${PL_ARGS[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}
python3 -I "$HERE/cluster.py" --inventory "$OUT/inventory.json" --out "$OUT/clusters.json"
python3 -I "$HERE/desc_lint.py" --inventory "$OUT/inventory.json" --usage "$OUT/usage.json" --out "$OUT/desc_lint.json"
echo "$OUT"
