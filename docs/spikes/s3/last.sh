#!/usr/bin/env bash
# Calls into helpers; the slow countNoInv case again with a timeout; startup cost re-measured.
cd "$(dirname "$0")"
O="-source 17 -Xlint:-options --progress"
cat /proc/loadavg
echo "=================== Calls"
bash ./run.sh Calls.java $O --timeout=30
echo "=================== countNoInv, --timeout=30"
bash ./run.sh LoopEntry.java $O --method=countNoInv --timeout=30
echo "=================== startup cost again: no method matches"
bash ./run.sh Decimal.java $O --method=doesNotExist | tail -2
cat /proc/loadavg
