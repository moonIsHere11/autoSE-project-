#!/usr/bin/env bash
# E7: entry-point spelling and classpath without the CProver jar.
source /w/common.sh
compile default /w/build/e7
echo "--- --function with descriptor"
jbmc -cp "/w/build/e7:$API" s2.Gotchas --function 's2.Gotchas.divZero:(JJ)J' > /w/out/e7_desc.txt 2>&1
echo "exit $? : $(tail -n1 /w/out/e7_desc.txt)"
echo "--- method name as the positional argument (no class, no --function)"
jbmc -cp "/w/build/e7:$API" 's2.Gotchas.divZero:(JJ)J' > /w/out/e7_positional.txt 2>&1
echo "exit $? : $(tail -n1 /w/out/e7_positional.txt)"
echo "--- harness without cprover-api.jar on -cp"
jbmc -cp "/w/build/e7" s2.Harness --function s2.Harness.reachGood --sat-solver cadical > /w/out/e7_noapi.txt 2>&1
echo "exit $? : $(grep -iE 'error|warn|CProver' /w/out/e7_noapi.txt | head -n3 | tr '\n' ' ') $(tail -n1 /w/out/e7_noapi.txt)"
echo "--- contradictory assumptions without cprover-api.jar (exit 0 = assume() still honoured)"
jbmc -cp "/w/build/e7" s2.Harness --function s2.Harness.contradictoryReach --sat-solver cadical > /w/out/e7_noapi_contra.txt 2>&1
echo "exit $? : $(tail -n1 /w/out/e7_noapi_contra.txt)"
