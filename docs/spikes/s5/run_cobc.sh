#!/usr/bin/env bash
# Spike S5 task 1: compile + run both samples and capture `cobc -E` output.
# Run from the repo root inside WSL:  bash docs/spikes/s5/run_cobc.sh
set -euo pipefail
IMG=cobol-verifier-toolchain:0.1.0
S5="$(cd "$(dirname "$0")" && pwd)"
docker run --rm --network none -v "$S5:/w" -w /w/samples "$IMG" bash -c '
  set -e
  mkdir -p /tmp/b /w/out
  for p in arith fileio; do
    echo "== cobc -x -std=default $p.cbl"
    cobc -x -std=default -o /tmp/b/$p $p.cbl && echo "   compiled OK"
    echo "== cobc -E -std=default $p.cbl -o out/$p.E.cob"
    cobc -E -std=default $p.cbl -o /w/out/$p.E.cob
    echo "   preprocessed OK: $(wc -l < /w/out/$p.E.cob) lines (source: $(wc -l < $p.cbl) lines)"
  done
  echo "== re-feed -E output to cobc -E -free (does it round-trip?)"
  cobc -E -free -std=default /w/out/arith.E.cob -o /w/out/arith.EE.cob 2>&1 | head -5 || true
  echo "== probe.cbl (lexical edge cases)"
  cobc -x -std=default -o /tmp/b/probe probe.cbl && echo "   compiled OK" && /tmp/b/probe
  cobc -E -std=default probe.cbl -o /w/out/probe.E.cob
  echo "== run arith (stdin: 3)"
  echo 3 | /tmp/b/arith
  echo "== run fileio"
  cd /tmp/b && cp /w/samples/custin.dat . && ./fileio && echo "-- rptout.dat:" && cat -A rptout.dat
'
