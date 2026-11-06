#!/usr/bin/env bash
# usage: bash docs/spikes/s3/all.sh File1 File2 ... -- [extra openjml options]
# Runs run.sh on each src/<File>.java; output to stdout and out/<File>.txt
cd "$(dirname "$0")"
files=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do files+=("$1"); shift; done
[ "${1-}" = "--" ] && shift
for f in "${files[@]}"; do
  echo "=================== $f"
  bash ./run.sh "$f.java" "$@" | tee "out/$f.txt"
done
