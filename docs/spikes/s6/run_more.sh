#!/bin/bash
# Spike S6 follow-up: ACCEPT window for other usages, -E literal handling, LS runtime settings.
set -u
IMG=cobol-verifier-toolchain:0.1.0
HERE=$(cd "$(dirname "$0")" && pwd)
docker run --rm --network none -v "$HERE:/src:ro" "$IMG" bash -c '
set -u
mkdir -p /tmp/b && cd /tmp/b && cp /src/S6MORE.cbl .
cobc -x -std=default S6MORE.cbl -o more || exit 1
for s in "-999" "-99" "12345" "-12345" "99999" "-1234.567" "123.456" "ABCDEF"; do
  echo "--- [$s]"; printf "%s\n%s\n%s\n%s\n%s\n" "$s" "$s" "$s" "$s" "$s" | ./more | head -1
done
printf "1\n1\n1\n1\n1\n" | ./more | tail -2
echo "### -E of literals / continuation"; cobc -E S6MORE.cbl | grep -n -E "LIT|CONT" | cat -A
echo "### runtime.cfg LINE SEQUENTIAL + misc defaults"
grep -n -E "^# Environment name:  COB_(LS_|FILE_PATH|SEQ_|VARSEQ|UNIX_LF|SYNC|DISPLAY|BELL|INSERT|PRETTY|DD_|FILENAME|ARGUMENT|COL)" -A6 /usr/local/share/gnucobol/config/runtime.cfg | grep -E "Environment name|Default|Purpose"
echo "### default.conf selected"
grep -E "^(binary-size|binary-byteorder|binary-truncate|pretty-display|filename-mapping|assign-clause|defaultbyte|default-byte|arithmetic-osvs|move-ibm|numeric-literal-length|pic-length|perform-osvs|align-record|complex-odo|init-justify|reserved-words|accept-display-extensions|line-col-zero-default|larger-redefines|ebcdic|sign-|hostsign|odo-without-to)" /usr/local/share/gnucobol/config/default.conf
'
