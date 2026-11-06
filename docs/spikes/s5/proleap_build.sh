#!/usr/bin/env bash
# Spike S5 task 2: fetch + build ProLeap COBOL parser in a THROWAWAY container
# (network enabled for this spike only), outside the repo.
# Usage (inside WSL, from repo root):  bash docs/spikes/s5/proleap_build.sh [workdir]
# Leaves: $WORK/proleap-cobol-parser-main/target/*.jar, $WORK/lib/*.jar (runtime deps).
# $WORK/m2 (Maven cache) is kept between runs; delete $WORK for a cold build.
# Cleanup afterwards (files are root-owned):
#   docker run --rm -v /tmp:/t cobol-verifier-toolchain:0.1.0 rm -rf /t/s5-proleap
set -euo pipefail
IMG=cobol-verifier-toolchain:0.1.0
WORK="${1:-/tmp/s5-proleap}"
COMMIT=d1bfe75bdd6d480f70c74c6345bcc02610ac30d3   # main @ 2026-03-01 (pom version 4.0.0)
mkdir -p "$WORK"
docker run --rm --memory 1500m -e MAVEN_OPTS=-Xmx768m -v "$WORK:/v" -w /v "$IMG" bash -c '
  set -e
  ms() { echo $(( ($2 - $1) / 1000000 )); }
  rm -rf /v/proleap-cobol-parser-main /v/lib /v/pl.zip
  t0=$(date +%s%N)
  curl -fsSL -o pl.zip https://github.com/uwol/proleap-cobol-parser/archive/'"$COMMIT"'.zip
  unzip -q pl.zip && mv proleap-cobol-parser-* proleap-cobol-parser-main
  t1=$(date +%s%N)
  cd proleap-cobol-parser-main
  # -Dmaven.test.skip=true: do not even compile the 775 test classes (-DskipTests still compiles them)
  mvn -B -q -Dmaven.test.skip=true -Dmaven.repo.local=/v/m2 package > /v/build.log 2>&1 || { tail -40 /v/build.log; exit 1; }
  t2=$(date +%s%N)
  mvn -B -q -Dmaven.repo.local=/v/m2 dependency:copy-dependencies -DincludeScope=runtime -DoutputDirectory=/v/lib >> /v/build.log 2>&1
  t3=$(date +%s%N)
  echo "download+unzip: $(ms $t0 $t1) ms"
  echo "mvn package (-Dmaven.test.skip=true): $(ms $t1 $t2) ms"
  echo "copy runtime deps: $(ms $t2 $t3) ms"
  sha256sum /v/pl.zip
  ls -la target/proleap-cobol-parser-4.0.0.jar
  echo "runtime deps:"; ls -la /v/lib
  du -sh /v/m2 /v/lib
'
