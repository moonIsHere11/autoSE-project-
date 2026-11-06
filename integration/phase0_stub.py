#!/usr/bin/env python3
"""Day-one Phase 0 stub (agreement section 9): serves `phase0 query <method> [args] --workspace W` from
hand-written files under W/kb/target/. Only what Phase 1 uses: toolchain, rules_for, gaps_for."""
import json
import sys
from pathlib import Path

a = sys.argv[1:]
ws = Path(a[a.index("--workspace") + 1])
method = a[1]
args = [x for x in a[2:] if x != "--workspace" and x != str(ws)]
t = ws / "kb" / "target"
if method == "toolchain":
    out = json.loads((t / "toolchain.json").read_text())
elif method in ("rules_for", "gaps_for"):
    f = "mapping_rules.json" if method == "rules_for" else "semantic_gaps.json"
    items = json.loads((t / f).read_text()) if (t / f).exists() else []
    keys = [k.strip().upper() for k in (args[0].split(",") if args else [])]
    field = "cobol_construct" if method == "rules_for" else "topic"
    out = [i for i in items if not keys or any(k in i[field].upper() or i[field].upper() in k for k in keys)] or items[:4]
else:
    print(f"unsupported in stub: {method}", file=sys.stderr)
    sys.exit(2)
print(json.dumps(out))
