#!/usr/bin/env bash
# E3b: second sweep on Harness.checkGood (add/sub): z3 without string refinement, arithmetic
# refinement, formula slicing, and per-property splitting (4 processes, one per output field).
source /w/common.sh
compile default /w/build/r17b
CP="/w/build/r17b:$API"
F=s2.Harness.checkGood
base=(jbmc s2.Harness --function "$F" -cp "$CP" --unwind 5 --unwinding-assertions)
run() { local name="$1"; shift; timed "/w/out/e3b_add_${name}.txt" timeout 900 "${base[@]}" "$@"; }
run cadical_solo       --sat-solver cadical
run z3_norefstr        --no-refine-strings --z3 &
run cadical_refarith   --sat-solver cadical --refine-arithmetic &
run cadical_slice      --sat-solver cadical --slice-formula &
wait
for k in 1 2 3 4; do
  run "cadical_prop$k" --sat-solver cadical --slice-formula --property "java::s2.Harness.checkGood:()V.assertion.$k" &
done
wait
for f in /w/out/e3b_add_*.txt; do echo "-- $(basename $f): $(grep -E 'Runtime decision' $f | tail -n1) | $(tail -n 1 $f)"; done
