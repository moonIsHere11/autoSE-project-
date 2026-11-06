#!/usr/bin/env bash
# E6: are a few frequently-suggested flags accepted by jbmc 6.8.0? (cheap probe on Gotchas.divZero)
source /w/common.sh
compile default /w/build/e6
for opt in --no-built-in-assertions --no-standard-checks --div-by-zero-check --no-div-by-zero-check \
           --java-assume-inputs-non-null "--max-nondet-array-length 3"; do
  # shellcheck disable=SC2086
  jbmc -cp "/w/build/e6:$API" s2.Gotchas --function s2.Gotchas.divZero $opt > /w/out/e6_flag.txt 2>&1
  echo "$opt -> exit $? : $(grep -E 'VERIFICATION|Usage|Unknown|unknown' /w/out/e6_flag.txt | head -n1)"
done
