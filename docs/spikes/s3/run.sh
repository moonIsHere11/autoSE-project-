#!/usr/bin/env bash
# usage: bash docs/spikes/s3/run.sh <File.java> [extra openjml options...]
# Runs OpenJML ESC on src/<File.java> inside the toolchain image; prints output, exit code, wall time.
cd "$(dirname "$0")"
f="$1"; shift
docker run --rm -v "$PWD:/w" -w /w cobol-verifier-toolchain:0.1.0 bash -c '
f="$1"; shift
start=$(date +%s%N)
bash ./openjml-linux --esc --os-name=linux "$@" "src/$f"
rc=$?
end=$(date +%s%N)
echo "### exit=$rc wall=$(( (end - start) / 1000000 ))ms"
' _ "$f" "$@" 2>&1
