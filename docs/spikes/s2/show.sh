#!/usr/bin/env bash
# Print the interesting (non-"SUCCESS", non-empty) lines of JBMC logs: show.sh <n-lines> <file>...
cd "$(dirname "$0")/out" || exit 1
n="$1"; shift
for f in "$@"; do
  echo "=== $f"
  grep -v -E ': SUCCESS$|^$|^Unwinding recursion|^aborting path' "$f" | head -n "$n"
done
