#!/usr/bin/env bash
# Counterexample / trace output, solver selection detail, bad --exec, timeout behaviour.
cd "$(dirname "$0")"
O="-source 17 -Xlint:-options"
echo "=================== counterexample"
bash ./run.sh Decimal.java $O --method=addTrunc5Buggy --counterexample > out/ce_counterexample.txt; tail -5 out/ce_counterexample.txt; wc -l out/ce_counterexample.txt
echo "=================== trace"
bash ./run.sh Decimal.java $O --method=addTrunc5Buggy --trace > out/ce_trace.txt; wc -l out/ce_trace.txt
echo "=================== trace+subexpressions"
bash ./run.sh Decimal.java $O --method=addTrunc5Buggy --trace --subexpressions > out/ce_subexpr.txt; wc -l out/ce_subexpr.txt
echo "=================== jmlverbose (which solver exec)"
bash ./run.sh Decimal.java $O --method=addTrunc5 --jmlverbose 2>&1 | grep -iE 'z3|solver|exec|prover' | head -20
echo "=================== bad exec"
bash ./run.sh Decimal.java $O --method=addTrunc5 --prover=z3 --exec=/nonexistent/z3
echo "=================== Hard, timeout=5"
bash ./run.sh Hard.java $O --progress --show-summary --method=fermat3 --timeout=5
echo "=================== Hard, timeout=20"
bash ./run.sh Hard.java $O --progress --show-summary --method=fermat3 --timeout=20
