#!/usr/bin/env bash
# E4: cost of add/sub, mul+rescale, general division, OCCURS loops. Usage: e4_cost.sh <tag> [jbmc opts...]
source /w/common.sh
tag="$1"; shift
B=/w/build/e4_$tag
compile default "$B"
P() {  # P <name> <class> <method> <unwind>
  local name="$1" cls="$2" m="$3" k="$4"
  timed "/w/out/e4_${tag}_${name}.txt" timeout 900 jbmc -cp "$B:$API" "$cls" --function "$cls.$m" \
    --unwind "$k" --unwinding-assertions "${OPTS[@]}"
}
OPTS=("$@")
P add_good   s2.Harness checkGood   5 &
P add_bug    s2.Harness checkBug    5 &
P mul_good   s2.Cost    mulRescale  5 &
P mul_bug    s2.Cost    mulRescaleBug 5 &
P div_good   s2.Cost    divRounded  5 &
P loop5      s2.Cost    loopSum5    6 &
P loop10     s2.Cost    loopSum10   11 &
wait
for f in /w/out/e4_${tag}_*.txt; do
  echo "-- $(basename $f): $(grep -E '^[0-9]+ variables' $f | tail -n1) | $(grep -E 'Runtime decision' $f | tail -n1) | $(tail -n 1 $f)"
done
