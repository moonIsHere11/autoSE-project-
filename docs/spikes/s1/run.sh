#!/bin/bash
# Spike S1: cobc build / run / -E / trace.  Run from the repo root:
#   bash docs/spikes/s1/run.sh
set -u
IMG=cobol-verifier-toolchain:0.1.0
HERE=$(cd "$(dirname "$0")" && pwd)
docker run --rm --network none -v "$HERE:/src:ro" "$IMG" bash -c '
set -u
mkdir -p /tmp/b && cd /tmp/b && cp /src/*.cbl /src/*.cpy .
echo "### cobc --version"; cobc --version | head -3
echo "### cobc --info (selected)"; cobc --info | grep -iE "version|build|binary|endian|gmp|math" | head -20
echo "### build S1PROG"; time cobc -x -std=default -I . S1PROG.cbl -o s1prog; echo "rc=$?"
echo "### run S1PROG with stdin 12.34 / 7"; printf "12.34\n7\n" | ./s1prog; echo "rc=$?"
echo "### cobc -E S1PROG (cat -A shows exact whitespace)"; cobc -E -std=default -I . S1PROG.cbl | cat -A | head -45
echo "### build traced variant"; cobc -x -std=default -ftraceall -I . S1PROG.cbl -o s1prog_t; echo "rc=$?"
echo "### default trace format to file"
printf "12.34\n7\n" | COB_SET_TRACE=Y COB_TRACE_FILE=/tmp/b/trace1.txt ./s1prog_t > /tmp/b/out1.txt; echo "rc=$?"
echo "--- stdout"; cat /tmp/b/out1.txt; echo "--- trace"; cat -A /tmp/b/trace1.txt | head -60
echo "### custom trace format %F|%I|%L|%S"
printf "12.34\n7\n" | COB_SET_TRACE=Y COB_TRACE_FILE=/tmp/b/trace2.txt COB_TRACE_FORMAT="%F|%I|%L|%S" ./s1prog_t > /dev/null
cat /tmp/b/trace2.txt | head -40
echo "### is stdout identical between traced and untraced builds?"
printf "12.34\n7\n" | ./s1prog > o_plain.txt; printf "12.34\n7\n" | COB_SET_TRACE=Y COB_TRACE_FILE=/tmp/b/t3.txt ./s1prog_t > o_traced.txt; cmp o_plain.txt o_traced.txt && echo IDENTICAL
echo "### timing: 200 runs of untraced binary"; time (for i in $(seq 200); do printf "12.34\n7\n" | ./s1prog > /dev/null; done)
echo "### runtime errors: S1ERR (divide by zero, missing file)"
cobc -x -std=default S1ERR.cbl -o s1err && { ./s1err; echo "rc=$?"; }
echo "### same with COB_CURRENT_DATE set, check env var is accepted"
echo "### sha256 stability of binary across two builds"
cobc -x -std=default -I . S1PROG.cbl -o a1 && cobc -x -std=default -I . S1PROG.cbl -o a2 && sha256sum a1 a2
echo "### preprocessed-source hash stability"
cobc -E -std=default -I . S1PROG.cbl | sha256sum; cobc -E -std=default -I . S1PROG.cbl | sha256sum
'
