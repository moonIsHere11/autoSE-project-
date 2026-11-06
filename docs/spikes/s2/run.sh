#!/usr/bin/env bash
# WSL-side launcher: runs docs/spikes/s2/<script>.sh inside the toolchain image.
# Usage (from repo root, in WSL):  bash docs/spikes/s2/run.sh e1_versions
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
script="$1"; shift || true
# -m/--memory-swap: cap the container so a runaway JBMC (string traces!) cannot OOM all of WSL.
exec docker run --rm -m "${S2_MEM:-5g}" --memory-swap "${S2_MEM:-5g}" -v "$here:/w" -w /w \
  cobol-verifier-toolchain:0.1.0 \
  bash "/w/${script}.sh" "$@"
