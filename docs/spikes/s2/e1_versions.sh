#!/usr/bin/env bash
# E1: does JBMC 6.8.0 accept javac-17 class files (v61)? Compare --release 17/11/8.
source /w/common.sh
for rel in default 11 8; do
  compile "$rel" "/w/build/r$rel"
  echo "== release=$rel  class version: $(javap -v -cp /w/build/r$rel s2.Harness | grep major)"
  timed "/w/out/e1_r${rel}_checkGood.txt" \
    jbmc s2.Harness --function s2.Harness.checkGood -cp "/w/build/r$rel:$API" \
      --unwind 5 --unwinding-assertions
  tail -n 4 "/w/out/e1_r${rel}_checkGood.txt"
done
