#!/bin/bash
# Spike S6: ACCEPT parsing, DISPLAY formats, layout, record encodings, time.
#   bash docs/spikes/s6/run.sh
set -u
IMG=cobol-verifier-toolchain:0.1.0
HERE=$(cd "$(dirname "$0")" && pwd)
docker run --rm --network none -v "$HERE:/src:ro" "$IMG" bash -c '
set -u
mkdir -p /tmp/b && cd /tmp/b && cp /src/*.cbl .
for p in S6ACC S6DISP S6FILE S6TIME; do cobc -x -std=default $p.cbl -o ${p,,} || echo "BUILD FAIL $p"; done
echo "### ACCEPT text -> numeric/alnum fields"
while IFS= read -r s; do
  echo "--- input [$s]"
  printf "%s\n%s\n%s\n%s\n%s\n%s\n" "$s" "$s" "$s" "$s" "$s" "$s" | ./s6acc 2>&1
done <<EOF
123
123.45
-5
+5
 12
12
5-
-0
0
abc
1a2

1234567
12.345
1,5
-12.5
.5
-99999.99
1e3
 -3.2
0012
12.3.4
--5
- 5
EOF
echo "### ACCEPT at EOF (fewer lines than ACCEPTs)"
printf "1\n" | ./s6acc; echo "rc=$?"
printf "" | ./s6acc; echo "rc=$?"
echo "### ACCEPT without trailing newline"; printf "42" | ./s6acc | head -2
echo "### DISPLAY formats + byte lengths"
./s6disp | cat -A
echo "### files"
printf "AB\nABCDEFGHIJ\n\nX   0012\nLAST" > LSIN.TXT
./s6file; echo "rc=$?"
echo "--- FIXOUT.DAT"; od -A d -t x1 -c FIXOUT.DAT
echo "--- LSOUT.TXT"; od -A d -c LSOUT.TXT
echo "--- PLAIN (ASSIGN TO PLAINNAME)"; ls -la; cat PLAIN* 2>/dev/null
echo "### time: no faking"
printf "a\nb\n" | ./s6time
echo "### time: COB_CURRENT_DATE"
printf "a\nb\n" | COB_CURRENT_DATE="2024/01/15 10:30:00" ./s6time
echo "### time: libfaketime frozen"
printf "a\nb\n" | LD_PRELOAD=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1 FAKETIME="2024-01-15 10:30:00" ./s6time
printf "a\nb\n" | LD_PRELOAD=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1 FAKETIME="2024-01-15 10:30:00" ./s6time
echo "### time: libfaketime + java"
mkdir -p j && cat > j/T.java <<JEOF
public class T { public static void main(String[] a) throws Exception {
  System.out.println(java.time.LocalDateTime.now() + " " + System.currentTimeMillis());
  Thread.sleep(50); System.out.println("slept ok"); } }
JEOF
javac -d j j/T.java && LD_PRELOAD=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1 FAKETIME="2024-01-15 10:30:00" FAKETIME_DONT_FAKE_MONOTONIC=1 timeout 10 java -cp j T; echo "rc=$?"
echo "### java startup time x10"
time (for i in $(seq 10); do java -Xshare:auto -XX:TieredStopAtLevel=1 -cp j T >/dev/null; done)
'
