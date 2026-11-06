#!/usr/bin/env bash
# Inspect the OpenJML installation inside the toolchain image (read-only).
cd "$(dirname "$0")"
docker run --rm -v "$PWD:/w" -w /w cobol-verifier-toolchain:0.1.0 bash -c '
set -x
cat /opt/openjml/version-info.txt
cat /opt/openjml/os-name.sh
ls -la /opt/openjml/Solvers-linux /opt/openjml/libs
cat /opt/openjml/openjml-java
cat /opt/openjml/setup-exports
ls /opt/openjml/jdk/bin
/opt/openjml/jdk/bin/java -version
which -a z3
z3 --version
/usr/bin/z3 --version
echo "PATH=$PATH"
cat /proc/version
cat /opt/openjml/openjml.properties-template
unzip -l /opt/openjml/libs/jSMTLIB.jar | grep -i properties
'
