# Sourced by the container-side experiment scripts.
set -uo pipefail
export LC_ALL=C
API=/usr/lib/cprover-api.jar
mkdir -p /w/out

# compile <release|default> <outdir>: compile all spike sources
compile() {
  local rel="$1" out="$2" flags=()
  [ "$rel" != default ] && flags=(--release "$rel")
  rm -rf "$out"; mkdir -p "$out"
  javac "${flags[@]}" -g -cp "$API" -d "$out" /w/src/s2/*.java
}

# timed <logfile> <cmd...>: run cmd, save stdout+stderr to logfile, print wall time + exit code
timed() {
  local log="$1"; shift
  local t0 t1 rc
  t0=$(date +%s.%N)
  "$@" > "$log" 2>&1; rc=$?
  t1=$(date +%s.%N)
  echo "$rc" > "$log.rc"
  printf '%-40s rc=%-3s wall=%6.2fs\n' "$(basename "$log")" "$rc" "$(awk "BEGIN{print $t1 - $t0}")"
  return 0
}
