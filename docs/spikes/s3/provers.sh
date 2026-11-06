#!/usr/bin/env bash
# Try the different solver binaries / prover names on Decimal.java (2 valid + 2 invalid methods expected
# for addTrunc/addTrunc5/addTrunc5Buggy/addTruncBuggy).
cd "$(dirname "$0")"
O="-source 17 -Xlint:-options --progress --show-summary"
for args in \
  "--prover=z3" \
  "--prover=z3_4_3" \
  "--prover=z3 --exec=/usr/bin/z3" \
  "--prover=z3 --exec=/opt/pyenv/bin/z3" \
  "--prover=z3 --exec=/opt/openjml/Solvers-linux/z3-4.12.6" \
  "--prover=cvc5" \
  "--prover=yices2" ; do
  echo "=================== $args"
  bash ./run.sh Decimal.java $O $args | grep -E 'Starting proof of Decimal.addTrunc5Buggy|Completed proof|Valid:|Invalid:|Error:|error|exit=|Exception'
done
