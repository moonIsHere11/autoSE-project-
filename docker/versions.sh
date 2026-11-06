#!/bin/bash
# Prints the exact toolchain versions as JSON. Recorded in every verifier report.
clean() { sed -e 's/\x1b\[[0-9;]*m//g' | tr -d '"\' | head -n1; }
first() { "$@" 2>&1 | clean; }
cat <<JSON
{
  "gnucobol": "$(first cobc --version)",
  "libcob": "$(first cobcrun --version)",
  "java": "$(first java -version)",
  "javac": "$(first javac -version)",
  "maven": "$(mvn -B -v 2>&1 | clean)",
  "jbmc": "$(first jbmc --version)",
  "cbmc": "$(first cbmc --version)",
  "openjml": "$(first openjml --version)",
  "openjml_release": "${OPENJML_VERSION:-21.0.28}",
  "z3": "$(first z3 --version)",
  "python": "$(first python3 --version)",
  "crosshair": "$(pip show crosshair-tool 2>/dev/null | grep -i '^version' | sed 's/.*: //' | clean)",
  "go": "$(first go version)",
  "libfaketime": "$(dpkg-query -W -f='${Version}' libfaketime 2>/dev/null)",
  "image_base": "ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852"
}
JSON
