#!/bin/bash
# Prints the exact toolchain versions as JSON. Recorded in every verifier report.
first() { "$@" 2>&1 | head -n1 | tr -d '"\\' ; }
cat <<EOF
{
  "gnucobol": "$(first cobc --version)",
  "libcob": "$(cobc --info 2>/dev/null | grep -m1 -i 'libcob version' | sed 's/.*: *//' | tr -d '"')",
  "java": "$(first java -version)",
  "javac": "$(first javac -version)",
  "maven": "$(first mvn -v)",
  "jbmc": "$(first jbmc --version)",
  "cbmc": "$(first cbmc --version)",
  "openjml": "$(first openjml --version)",
  "z3": "$(first z3 --version)",
  "python": "$(first python3 --version)",
  "crosshair": "$(first crosshair --version)",
  "go": "$(first go version)",
  "libfaketime": "$(dpkg-query -W -f='${Version}' libfaketime 2>/dev/null)",
  "image_base": "ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852"
}
EOF
