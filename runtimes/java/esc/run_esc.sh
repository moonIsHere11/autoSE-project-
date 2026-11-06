#!/usr/bin/env bash
# OpenJML ESC on the JML-annotated static core (cobolrt.Num, cobolrt.Alnum).
# Run from the repo root (WSL):  bash runtimes/java/esc/run_esc.sh
# Writes runtimes/java/esc/esc.log; flags per docs/spikes/S3.md and DECISIONS D11.
set -u
cd "$(dirname "$0")/../../.."
docker run --rm --network none --memory 2g -v "$PWD:/w" -w /w \
  -e OPENJML_INSTALL=/opt/openjml -e SMT_SOLVER_DIR=/opt/openjml/Solvers-linux \
  cobol-verifier-toolchain:0.1.0 bash -c '
    mkdir -p /tmp/esc && cp runtimes/java/src/cobolrt/{Num,Alnum,Pic,Round,Usage}.java /tmp/esc/
    timeout -k 10 3000 bash docs/spikes/s3/openjml-linux --esc --os-name=linux -source 17 -Xlint:-options \
      --progress --show-summary --timeout=60 --check-feasibility=precondition \
      -sourcepath /tmp/esc -d /tmp/esc-out /tmp/esc/Num.java /tmp/esc/Alnum.java
    echo "exit=$?"' > runtimes/java/esc/esc.log 2>&1
grep -E "Completed proof|Skipping|exit=|Summary|Valid|Invalid|Infeasible|Timeout|Error" runtimes/java/esc/esc.log