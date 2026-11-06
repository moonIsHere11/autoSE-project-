#!/usr/bin/env bash
# E3: solver / option sweep on the add+subtract equivalence (Harness.checkGood), run in parallel.
source /w/common.sh
compile default /w/build/r17
CP="/w/build/r17:$API"
F=${1:-s2.Harness.checkGood}
tag=${2:-add}
base=(jbmc s2.Harness --function "$F" -cp "$CP" --unwind 5 --unwinding-assertions)
run() { local name="$1"; shift; timed "/w/out/e3_${tag}_${name}.txt" timeout 900 "${base[@]}" "$@"; }
run minisat_default &
run norefstr          --no-refine-strings &
run cadical           --sat-solver cadical &
run norefstr_cadical  --no-refine-strings --sat-solver cadical &
run z3                --z3 &
run norefstr_minisat_nopre --no-refine-strings --no-sat-preprocessor &
wait
for f in /w/out/e3_${tag}_*.txt; do echo "-- $(basename $f): $(grep -E 'Runtime Solver|Runtime decision' $f | tr '\n' ' ') | $(tail -n 1 $f)"; done
