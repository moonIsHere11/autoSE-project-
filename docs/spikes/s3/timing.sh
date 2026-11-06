#!/usr/bin/env bash
# Exit codes for an all-verified run, fixed start-up cost, batch run, feasibility check.
cd "$(dirname "$0")"
O="-source 17 -Xlint:-options"
echo "=================== all verified (expect exit 0)"
bash ./run.sh Decimal.java $O --progress --method=addTrunc5
echo "=================== startup cost: no method matches"
bash ./run.sh Decimal.java $O --method=doesNotExist
echo "=================== startup cost: --check only (parse+typecheck JML, no proving)"
docker run --rm -v "$PWD:/w" -w /w cobol-verifier-toolchain:0.1.0 bash -c '
s=$(date +%s%N); bash ./openjml-linux --check -source 17 -Xlint:-options src/Decimal.java; echo "### exit=$? wall=$(( ($(date +%s%N)-s)/1000000 ))ms"'
echo "=================== J17 features + vacuous precondition (default)"
bash ./run.sh J17.java $O --progress --show-summary
echo "=================== J17 with --check-feasibility=precondition"
bash ./run.sh J17.java $O --progress --method=vacuous --check-feasibility=precondition
echo "=================== batch: 4 files in one JVM"
docker run --rm -v "$PWD:/w" -w /w cobol-verifier-toolchain:0.1.0 bash -c '
s=$(date +%s%N); bash ./openjml-linux --esc --os-name=linux -source 17 -Xlint:-options --show-summary src/Decimal.java src/Account.java src/Status.java src/Loops.java | tail -12; echo "### exit=$? wall=$(( ($(date +%s%N)-s)/1000000 ))ms"'
echo "=================== --release 17 (fails?)"
bash ./run.sh Account.java --release 17 | head -5;
echo "=================== --verify-exit=0"
bash ./run.sh Account.java $O --verify-exit=0 | tail -2
