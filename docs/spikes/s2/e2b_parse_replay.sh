#!/usr/bin/env bash
# E2b: classify every E2 JSON run, then replay the extracted counterexamples with plain `java`.
source /w/common.sh
for f in /w/out/e2_*.json; do
  rc=$(cat "$f.rc" 2>/dev/null || echo 99)
  echo "### $(basename "$f") (exit $rc)"
  python3 /w/parse_jbmc.py "$f" "$rc" | python3 -c '
import json,sys; d=json.load(sys.stdin)
print("verdict:", d["verdict"]); print("failed:", [(x["property"], x["line"]) for x in d["failed"]])
print("inputs:", d["inputs"]); print("errors:", [e[:160] for e in d["errors"] if e])'
done

# Replay: no CProver on the classpath -> proves the replay does not depend on the model checker.
replay() {  # replay <Good|Bug|BugTrunc> <json>
  local args
  args=$(python3 /w/parse_jbmc.py "$2" 10 | python3 -c '
import json,sys; i=json.load(sys.stdin)["inputs"]
print(" ".join(str(i[k]) for k in ("in_wsA","in_wsB","in_wsC","in_wsD")))')
  echo "### replay $1 with: $args"
  java -cp /w/build/e2 s2.Replay "$1" $args; echo "exit=$?"
}
replay Bug      /w/out/e2_checkBug.json
replay Good     /w/out/e2_checkBug.json
replay BugTrunc /w/out/e2_checkBugTrunc.json
replay Good     /w/out/e2_checkBugTrunc.json
