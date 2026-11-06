#!/usr/bin/env bash
# Run a command inside the toolchain image with docs/spikes/s3 mounted at /w.
# usage: bash docs/spikes/s3/dock.sh '<bash command>'
cd "$(dirname "$0")"
exec docker run --rm -v "$PWD:/w" -w /w cobol-verifier-toolchain:0.1.0 bash -c "$1"
