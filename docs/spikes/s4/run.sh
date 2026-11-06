#!/usr/bin/env bash
# S4 spike driver. Run from WSL (any cwd):  bash docs/spikes/s4/run.sh q1 q2 ...
# Runs inner.sh inside the pinned toolchain image, sandboxed like the verifier will (no network).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
exec docker run --rm --network none \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/w \
  -v "$HERE:/w" -w /w \
  cobol-verifier-toolchain:0.1.0 bash /w/inner.sh "$@"
