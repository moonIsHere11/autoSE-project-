#!/usr/bin/env bash
# E5b: why do the PIC X probes fail? Traces + char[]-only variants + JDK class extraction for Math.
source /w/common.sh
compile default /w/build/e5br17
compile 8 /w/build/e5br8
G() { local rel="$1"; shift; timeout 600 jbmc -cp "/w/build/e5b$rel:$API" s2.Gotchas --unwind 10 --unwinding-assertions "$@"; }
timed /w/out/e5b_picXCharArray_trace.txt  G r17 --function s2.Gotchas.picXCharArray --trace --compact-trace &
timed /w/out/e5b_picXCharArrayLoop.txt    G r17 --function s2.Gotchas.picXCharArrayLoop &
timed /w/out/e5b_picXCharArrayLoopBug.txt G r17 --function s2.Gotchas.picXCharArrayLoopBug --trace --compact-trace &
timed /w/out/e5b_picXBuilder_trace.txt    G r17 --function s2.Gotchas.picXStringBuilder --trace --compact-trace &
timed /w/out/e5b_picXConcat_r8_trace.txt  G r8  --function s2.Gotchas.picXStringConcat --trace --compact-trace &
timed /w/out/e5b_picXConcat_r17_trace.txt G r17 --function s2.Gotchas.picXStringConcat --trace --compact-trace &
timed /w/out/e5b_picXBuilder_printable.txt G r17 --function s2.Gotchas.picXStringBuilder --string-printable --max-nondet-string-length 16 &
wait
# Can real JDK bytecode replace a stub? Extract java/lang/Math.class from the JDK 17 jimage.
JH=$(dirname "$(dirname "$(readlink -f "$(which javac)")")")
rm -rf /w/build/jdkx; mkdir -p /w/build/jdkx
"$JH/bin/jimage" extract --dir /w/build/jdkx --include 'regex:/java.base/java/lang/Math\.class' "$JH/lib/modules"
ls -la /w/build/jdkx/java.base/java/lang/ 2>&1 | head
timed /w/out/e5b_mathAbs_jdkMath.txt timeout 600 jbmc -cp "/w/build/e5br17:/w/build/jdkx/java.base:$API" s2.Gotchas \
  --function s2.Gotchas.mathAbs --unwind 10 --unwinding-assertions
tail -n 3 /w/out/e5b_mathAbs_jdkMath.txt
