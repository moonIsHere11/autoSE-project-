#!/usr/bin/env bash
# The exact command line recommended for T3 (see S3.md), run on several toys in ONE JVM.
cd "$(dirname "$0")"
cat /proc/loadavg
s=$(date +%s%N)
timeout --kill-after=10s 600s \
docker run --rm --network=none -v "$PWD:/w" -w /w cobol-verifier-toolchain:0.1.0 \
  bash ./openjml-linux --esc --os-name=linux -source 17 -Xlint:-options \
    --progress --show-summary \
    --prover=z3 --exec=/opt/openjml/Solvers-linux/z3-4.16.0 \
    --timeout=30 --check-feasibility=precondition \
    src/Decimal.java src/Account.java src/Status.java src/J17.java
echo "### exit=$? wall=$(( ($(date +%s%N)-s)/1000000 ))ms"
cat /proc/loadavg
