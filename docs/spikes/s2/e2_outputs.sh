#!/usr/bin/env bash
# E2: output modes, exit codes, and the four outcome classes (pass / cex / unwind / tool error).
source /w/common.sh
B=/w/build/e2
compile default "$B"
CP="$B:$API"
J=(jbmc -cp "$CP" --unwind 5 --unwinding-assertions --sat-solver cadical)

# (b) assertion violated -> counterexample (json + plain text)
timed /w/out/e2_checkBug.json      "${J[@]}" s2.Harness --function s2.Harness.checkBug --json-ui --trace &
timed /w/out/e2_checkBug.txt       "${J[@]}" s2.Harness --function s2.Harness.checkBug --trace &
timed /w/out/e2_checkBug.xml       "${J[@]}" s2.Harness --function s2.Harness.checkBug --xml-ui --trace &
timed /w/out/e2_checkBugTrunc.json "${J[@]}" s2.Harness --function s2.Harness.checkBugTrunc --json-ui --trace &
# (a) all hold, json
timed /w/out/e2_checkGood.json     "${J[@]}" s2.Harness --function s2.Harness.checkGood --json-ui &
# (c) unwinding assertion violated: OCCURS(5) loop with --unwind 3
timed /w/out/e2_loop5_unwind3.json jbmc -cp "$CP" --unwind 3 --unwinding-assertions --sat-solver cadical \
      s2.Cost --function s2.Cost.loopSum5 --json-ui --trace &
# vacuity probes
timed /w/out/e2_reachGood.json          "${J[@]}" s2.Harness --function s2.Harness.reachGood --json-ui --trace &
timed /w/out/e2_contradictoryBug.json   "${J[@]}" s2.Harness --function s2.Harness.contradictoryBug --json-ui &
timed /w/out/e2_contradictoryReach.json "${J[@]}" s2.Harness --function s2.Harness.contradictoryReach --json-ui &
# (d) tool errors
timed /w/out/e2_err_nofunc.json   "${J[@]}" s2.Harness --function s2.Harness.noSuchMethod --json-ui &
timed /w/out/e2_err_noclass.json  "${J[@]}" s2.NoSuchClass --json-ui &
timed /w/out/e2_err_badopt.json   "${J[@]}" s2.Harness --function s2.Harness.checkGood --json-ui --no-such-option &
timed /w/out/e2_err_nocp.json     jbmc --unwind 5 s2.Harness --function s2.Harness.checkGood --json-ui &
wait
