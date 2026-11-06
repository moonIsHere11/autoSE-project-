#!/usr/bin/env bash
# Spike S5 task 2: run ProLeap (built by proleap_build.sh) on the samples, offline.
# Usage (inside WSL, from repo root):  bash docs/spikes/s5/proleap_parse.sh [workdir]
set -euo pipefail
IMG=cobol-verifier-toolchain:0.1.0
WORK="${1:-/tmp/s5-proleap}"
S5="$(cd "$(dirname "$0")" && pwd)"
docker run --rm --network none --memory 1g -e REPEAT="${REPEAT:-3}" -v "$WORK:/v" -v "$S5:/w" -w /tmp "$IMG" bash -c '
  set -u
  ms() { echo $(( ($2 - $1) / 1000000 )); }
  CP="/v/proleap-cobol-parser-main/target/proleap-cobol-parser-4.0.0.jar:/v/lib/*"
  mkdir -p /tmp/cls /tmp/in /w/out/proleap
  t0=$(date +%s%N); javac -d /tmp/cls -cp "$CP" /w/ProLeapDump.java; t1=$(date +%s%N)
  echo "javac ProLeapDump.java: $(ms $t0 $t1) ms"
  t0=$(date +%s%N); java -version 2>/dev/null; java -cp /tmp/cls -version >/dev/null 2>&1; t1=$(date +%s%N)
  echo "bare JVM start (java -version): $(ms $t0 $t1) ms"
  # inputs: original fixed-format sources (ProLeap does its own COPY), and cobc -E output
  cp /w/samples/*.cbl /w/samples/*.cpy /tmp/in/
  for p in arith fileio probe; do
    cp /w/out/$p.E.cob /tmp/in/$p.E.raw.cob                                 # with #line markers
    sed "s/^#line .*$//" /w/out/$p.E.cob > /tmp/in/$p.E.cob                  # #line -> blank line
  done
  run() {  # name file format [paragraph]
    t0=$(date +%s%N)
    java -Xmx512m -Drepeat=${REPEAT:-0} -cp "/tmp/cls:$CP" ProLeapDump "$2" "$3" ${4:-} > /w/out/proleap/$1.json 2> /w/out/proleap/$1.err
    rc=$?; t1=$(date +%s%N)
    printf "%-22s %-8s rc=%d wall=%5d ms  %s\n" "$1" "$3" $rc "$(ms $t0 $t1)" \
      "$(grep -oE "\"(analyze|warm_min)_ms\":[0-9-]*" /w/out/proleap/$1.json) $(head -c 300 /w/out/proleap/$1.err | tr "\n" " ")"
  }
  run arith.fixed      /tmp/in/arith.cbl        FIXED  CLASSIFY-PARA
  run fileio.fixed     /tmp/in/fileio.cbl       FIXED  1000-READ
  run probe.fixed      /tmp/in/probe.cbl        FIXED
  run arith.E.tandem   /tmp/in/arith.E.cob      TANDEM CLASSIFY-PARA
  run fileio.E.tandem  /tmp/in/fileio.E.cob     TANDEM 1000-READ
  run probe.E.tandem   /tmp/in/probe.E.cob      TANDEM
  run arith.E.raw      /tmp/in/arith.E.raw.cob  TANDEM
  run arith.E.variable /tmp/in/arith.E.cob      VARIABLE
'
