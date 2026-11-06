#!/usr/bin/env bash
# Remaining checks: wrapper-less one-liner, which solver binary is used, docker overhead,
# batch summary, LoopInvariantBeforeLoop message.
cd "$(dirname "$0")"
IMG=cobol-verifier-toolchain:0.1.0
J="/opt/openjml/jdk/bin/javac -J--patch-module=jdk.compiler=/opt/openjml/libs/jSMTLIB.jar"
echo "=================== one-liner, no wrapper, with env"
docker run --rm -v "$PWD:/w" -w /w -e OPENJML_INSTALL=/opt/openjml -e SMT_SOLVER_DIR=/opt/openjml/Solvers-linux $IMG \
  $J --esc -source 17 -Xlint:-options --method=deposit src/Account.java; echo "### exit=$?"
echo "=================== one-liner, no wrapper, NO env"
docker run --rm -v "$PWD:/w" -w /w $IMG \
  $J --esc -source 17 -Xlint:-options --method=deposit src/Account.java 2>&1 | head -6; echo "### exit=${PIPESTATUS[0]}"
echo "=================== which solver binary: SMT_SOLVER_DIR=/tmp (default prover)"
docker run --rm -v "$PWD:/w" -w /w -e SMT_SOLVER_DIR=/tmp $IMG bash ./openjml-linux --esc -source 17 -Xlint:-options --method=deposit src/Account.java 2>&1 | head -3
echo "=================== which solver binary: SMT_SOLVER_DIR=/tmp --prover=z3"
docker run --rm -v "$PWD:/w" -w /w -e SMT_SOLVER_DIR=/tmp $IMG bash ./openjml-linux --esc -source 17 -Xlint:-options --method=deposit --prover=z3 src/Account.java 2>&1 | head -3
echo "=================== docker overhead"
s=$(date +%s%N); docker run --rm $IMG true; echo "docker run true: $(( ($(date +%s%N)-s)/1000000 ))ms"
s=$(date +%s%N); docker run --rm $IMG bash ./dummy 2>/dev/null; docker run --rm -v "$PWD:/w" -w /w $IMG bash ./openjml-linux --version; echo "docker+openjml --version: $(( ($(date +%s%N)-s)/1000000 ))ms"
echo "=================== batch summary"
docker run --rm -v "$PWD:/w" -w /w $IMG bash -c '
s=$(date +%s%N); bash ./openjml-linux --esc --os-name=linux -source 17 -Xlint:-options --show-summary src/Decimal.java src/Account.java src/Status.java src/Loops.java > out/batch.txt 2>&1; rc=$?; tail -12 out/batch.txt; echo "### exit=$rc wall=$(( ($(date +%s%N)-s)/1000000 ))ms"'
echo "=================== LoopInvariantBeforeLoop"
bash ./run.sh LoopEntry.java -source 17 -Xlint:-options --progress
