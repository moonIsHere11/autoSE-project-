"""`phase0 query context_packet UNIT [BUDGET]`: the sections of Phase 1's context pack
(`phase1/phase1/cobol/insight.py` `context_pack`, same titles and budget shares), built from KB facts
so Phase 1 can switch to the KB without changing its prompts."""

from __future__ import annotations

from collections import Counter
from typing import Any

from phase0.query import KnowledgeBase
from phase0.schema import Field_, Unit

SEVERITY = {"high": 3, "medium": 2, "low": 1}


class Packet:
    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.sections: dict[str, str] = {}

    def add(self, title: str, body: str, share: float) -> None:
        cap = int(self.budget * share)
        if len(body) > cap:
            body = body[:cap].rsplit("\n", 1)[0] + "\n...[truncated; use source_text/get_unit for more]"
        if body.strip():
            self.sections[title] = body

    def text(self) -> str:
        return "\n\n".join(f"## {t}\n{b}" for t, b in self.sections.items())


def type_text(f: Field_) -> str:
    st = f.semantic_type
    if st.kind == "decimal":
        sign = "U"
        if st.signed:
            sign = "S"
        return f"decimal({st.digits},{st.scale},{sign})"
    if st.length:
        return f"{st.kind}[{st.length}]"
    return st.kind


def field_rows(kb: KnowledgeBase, u: Unit) -> list[str]:
    rows: list[str] = []
    for f in kb.fields_of(u.unit_id):
        rw = ""
        if f.field_id in u.reads:
            rw += "R"
        if f.field_id in u.writes:
            rw += "W"
        pic = f.pic or "(group)"
        rows.append(f"{rw:2} {f.field_id}  PIC {pic} {f.usage}  {type_text(f)}")
    return rows


def scope_text(u: Unit) -> str:
    if u.unsupported:
        return "unsupported:" + ",".join(u.unsupported)
    return "in_scope"


def fix_hint(kb: KnowledgeBase, gap_id: str) -> str:
    for g in kb.gaps:
        if g.gap_id == gap_id:
            return g.required_handling.split(". ")[0]
    return ""


def neighbours(kb: KnowledgeBase, u: Unit) -> tuple[Counter[str], Counter[str], Counter[str]]:
    """(units feeding my reads, units consuming my writes, units sharing any field) in my program."""
    feeds: Counter[str] = Counter()
    consumes: Counter[str] = Counter()
    mates: Counter[str] = Counter()
    mine_r, mine_w = set(u.reads), set(u.writes)
    for o in kb.units.values():
        if o.unit_id == u.unit_id or o.program != u.program or o.kind != "paragraph":
            continue
        a = len(mine_r & set(o.writes))
        b = len(mine_w & set(o.reads))
        shared = len((mine_r | mine_w) & (set(o.reads) | set(o.writes)))
        if a:
            feeds[o.unit_id] = a
        if b:
            consumes[o.unit_id] = b
        if shared:
            mates[o.unit_id] = shared
    return feeds, consumes, mates


def context_packet(kb: KnowledgeBase, unit_id: str, budget: int) -> dict[str, Any]:
    u = kb.get_unit(unit_id)
    p = Packet(budget)
    p.add("Unit source", kb.source_text(unit_id), 0.40)
    p.add("Fields (type table)", "\n".join(field_rows(kb, u)[:40]), 0.20)
    hazards = sorted(u.hazards, key=lambda h: (-SEVERITY[h.severity], h.line))
    p.add("Semantic hazards to handle (static scan)", "\n".join(
        f"- [{h.severity}] {h.gap_id} line {h.line}: {h.detail}  => {fix_hint(kb, h.gap_id)}" for h in hazards[:12]), 0.22)
    callees = [kb.units[c] for c in u.performs if c in kb.units]
    p.add("Callees (already migrated first - bottom-up)", "\n".join(
        f"- {c.unit_id}: reads {len(c.reads)} writes {len(c.writes)} fields, {scope_text(c)}" for c in callees[:10]),
          0.06)
    feeds, consumes, mates = neighbours(kb, u)
    if feeds or consumes:
        p.add("Data dependences (who feeds me / who consumes me)",
              "feeds me: " + ", ".join(f"{k}({v})" for k, v in feeds.most_common(5)) +
              "\nconsumes my output: " + ", ".join(f"{k}({v})" for k, v in consumes.most_common(5)), 0.06)
    p.add("Module (cluster) mates - share state, keep conventions consistent",
          ", ".join(k for k, _ in mates.most_common(12)), 0.06)
    return {"unit_id": unit_id, "budget": budget, "sections": p.sections, "text": p.text()}
