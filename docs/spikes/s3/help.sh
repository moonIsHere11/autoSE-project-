#!/usr/bin/env bash
cd "$(dirname "$0")"
docker run --rm -v "$PWD:/w" -w /w cobol-verifier-toolchain:0.1.0 bash -c '
bash ./openjml-linux --help > out/help.txt 2>&1; echo "help exit=$?"
ls /opt/openjml/specs | head; ls /opt/openjml/specs/java/math/ 2>&1
'
