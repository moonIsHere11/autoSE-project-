"""`phase0 query`: the nine contract methods (agreement 4.1) plus additive ones, read from kb/ files.

Unknown ids raise QueryError with the valid ids and the closest matches ("errors that teach").
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import Any

from phase0 import jsonio
from phase0.schema import CallGraph, Coverage, DataFlow, Field_, Gap, Rule, Toolchain, Unit


class QueryError(LookupError):
    pass


def _teach(kind: str, wanted: str, valid: list[str]) -> QueryError:
    close = difflib.get_close_matches(wanted, valid, n=3, cutoff=0.5)
    shown = ", ".join(valid[:40])
    if len(valid) > 40:
        shown += f", ... ({len(valid)} total)"
    msg = f"unknown {kind} {wanted!r}."
    if close:
        msg += f" Did you mean: {', '.join(close)}?"
    msg += f" Valid {kind}s: {shown or '(none: is kb/ built?)'}"
    return QueryError(msg)


def split_list(arg: str) -> list[str]:
    return [p.strip() for p in arg.split(",") if p.strip()]


class KnowledgeBase:
    def __init__(self, kb: Path, source: Path) -> None:
        if not (kb / "manifest.json").exists():
            raise QueryError(f"no KB at {kb}: run `phase0 build --workspace {kb.parent}` first")
        self.kb = kb
        self.source = source

    def _list(self, rel: str) -> list[Any]:
        path = self.kb / rel
        if not path.exists():
            return []
        data = jsonio.read(path)
        if not isinstance(data, list):
            raise QueryError(f"{rel} is not a JSON list")
        return data

    @cached_property
    def units(self) -> dict[str, Unit]:
        return {u.unit_id: u for u in (Unit.model_validate(x) for x in self._list("source/units.json"))}

    @cached_property
    def fields(self) -> dict[str, Field_]:
        return {f.field_id: f for f in (Field_.model_validate(x) for x in self._list("source/data_dictionary.json"))}

    @cached_property
    def rules(self) -> list[Rule]:
        return [Rule.model_validate(x) for x in self._list("target/mapping_rules.json")]

    @cached_property
    def gaps(self) -> list[Gap]:
        return [Gap.model_validate(x) for x in self._list("target/semantic_gaps.json")]

    @cached_property
    def call_graph(self) -> CallGraph:
        path = self.kb / "source" / "call_graph.json"
        if not path.exists():
            return CallGraph(edges=[])
        return CallGraph.model_validate(jsonio.read(path))

    @cached_property
    def data_flow(self) -> DataFlow:
        path = self.kb / "source" / "data_flow.json"
        if not path.exists():
            return DataFlow(fields=[], files=[])
        return DataFlow.model_validate(jsonio.read(path))

    # ---- contract methods ----------------------------------------------------------------
    def list_units(self) -> list[Unit]:
        return list(self.units.values())

    def get_unit(self, unit_id: str) -> Unit:
        unit = self.units.get(unit_id)
        if unit is None:
            raise _teach("unit_id", unit_id, list(self.units))
        return unit

    def source_text(self, unit_id: str) -> str:
        span = self.get_unit(unit_id).span
        lines = (self.source / span.file).read_text("latin-1").splitlines()
        return "\n".join(lines[span.start_line - 1 : span.end_line]) + "\n"

    def get_field(self, field_id: str) -> Field_:
        fld = self.fields.get(field_id)
        if fld is None:
            raise _teach("field_id", field_id, list(self.fields))
        return fld

    def callers(self, unit_id: str) -> list[str]:
        self.get_unit(unit_id)
        return sorted({e.src for e in self.call_graph.edges if e.dst == unit_id and e.kind in CONTROL_KINDS})

    def callees(self, unit_id: str) -> list[str]:
        self.get_unit(unit_id)
        return sorted({e.dst for e in self.call_graph.edges if e.src == unit_id and e.kind in CONTROL_KINDS})

    def rules_for(self, constructs: list[str]) -> list[Rule]:
        return _match(self.rules, constructs, lambda r: (r.rule_id, r.cobol_construct, " ".join(r.gap_ids)), "rule")

    def gaps_for(self, topics: list[str]) -> list[Gap]:
        return _match(self.gaps, topics, lambda g: (g.gap_id, g.topic, " ".join(g.rule_ids)), "gap")

    def toolchain(self) -> Toolchain:
        return Toolchain.model_validate(jsonio.read(self.kb / "target" / "toolchain.json"))

    # ---- additive methods (contract 1.1) ---------------------------------------------------
    def writers_of(self, field_id: str) -> list[str]:
        self.get_field(field_id)
        return sorted(u.unit_id for u in self.units.values() if field_id in u.writes)

    def readers_of(self, field_id: str) -> list[str]:
        self.get_field(field_id)
        return sorted(u.unit_id for u in self.units.values() if field_id in u.reads)

    def fields_of(self, unit_id: str) -> list[Field_]:
        unit = self.get_unit(unit_id)
        ids = sorted(set(unit.reads) | set(unit.writes))
        return [self.fields[i] for i in ids if i in self.fields]

    def hazards_for(self, unit_id: str) -> list[dict[str, object]]:
        return [h.model_dump(mode="json") for h in self.get_unit(unit_id).hazards]

    def coverage(self) -> Coverage:
        path = self.kb / "source" / "coverage.json"
        if not path.exists():
            raise QueryError("coverage.json not built yet")
        return Coverage.model_validate(jsonio.read(path))


CONTROL_KINDS = frozenset({"perform", "perform-thru", "goto", "call"})


def _match(items: list[Any], keys: list[str], text: Callable[[Any], tuple[str, str, str]], kind: str) -> list[Any]:
    """Exact id first, then case-insensitive substring of construct/topic; no keys means all."""
    if not keys:
        return items
    out: list[Any] = []
    for key in keys:
        k = key.upper()
        hits = [i for i in items if text(i)[0].upper() == k]
        if not hits:
            hits = [i for i in items if k in text(i)[1].upper() or k in text(i)[2].upper()]
        for h in hits:
            if h not in out:
                out.append(h)
    if not out:
        valid = [f"{text(i)[0]} ({text(i)[1]})" for i in items]
        raise QueryError(f"no {kind} matches {keys}. Valid {kind}s: " + "; ".join(valid))
    return out
