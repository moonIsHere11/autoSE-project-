#!/usr/bin/env bash
# Summarise JBMC logs matching a glob: bash docs/spikes/s2/peek.sh 'e3_*'
cd "$(dirname "$0")/out" || exit 1
for f in $1; do
  printf '%s: %s | %s | %s\n' "$f" \
    "$(grep -E '^[0-9]+ variables' "$f" | tail -n1)" \
    "$(grep -E 'Runtime decision procedure' "$f" | tail -n1)" \
    "$(tail -n1 "$f")"
done
