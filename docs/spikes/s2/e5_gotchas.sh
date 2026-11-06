#!/usr/bin/env bash
# E5: default checks (exceptions, null inputs), JDK library calls, PIC X via char[] / String.
source /w/common.sh
compile default /w/build/e5r17
compile 8 /w/build/e5r8
G() { local rel="$1"; shift; timeout 600 jbmc -cp "/w/build/e5$rel:$API" s2.Gotchas --unwind 10 --unwinding-assertions "$@"; }

timed /w/out/e5_divZero.txt              G r17 --function s2.Gotchas.divZero --trace --compact-trace &
timed /w/out/e5_arrIdx.txt               G r17 --function s2.Gotchas.arrIdx --trace --compact-trace &
timed /w/out/e5_nullIn.txt               G r17 --function s2.Gotchas.nullIn &
timed /w/out/e5_nullIn_nonnull.txt       G r17 --function s2.Gotchas.nullIn --java-assume-inputs-non-null &
timed /w/out/e5_explicitThrow.txt        G r17 --function s2.Gotchas.explicitThrow &
timed /w/out/e5_explicitThrow_noexc.txt  G r17 --function s2.Gotchas.explicitThrow --disable-uncaught-exception-check &
timed /w/out/e5_divZero_throwrt.txt      G r17 --function s2.Gotchas.divZero --throw-runtime-exceptions &
timed /w/out/e5_mathAbs.txt              G r17 --function s2.Gotchas.mathAbs --trace --compact-trace &
timed /w/out/e5_bigDecimal.txt           G r17 --function s2.Gotchas.bigDecimalCandidate --trace --compact-trace &
wait
timed /w/out/e5_picXCharArray.txt        G r17 --function s2.Gotchas.picXCharArray &
timed /w/out/e5_picXCharArray_norefstr.txt G r17 --function s2.Gotchas.picXCharArray --no-refine-strings &
timed /w/out/e5_picXConcat_r17.txt       G r17 --function s2.Gotchas.picXStringConcat &
timed /w/out/e5_picXConcat_r8.txt        G r8  --function s2.Gotchas.picXStringConcat &
timed /w/out/e5_picXBuilder_r17.txt      G r17 --function s2.Gotchas.picXStringBuilder &
timed /w/out/e5_picXBug_r17.txt          G r17 --function s2.Gotchas.picXStringBug --trace --compact-trace &
timed /w/out/e5_picXBuilder_norefstr.txt G r17 --function s2.Gotchas.picXStringBuilder --no-refine-strings &
wait
