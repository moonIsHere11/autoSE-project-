"""Byte-level storage model: which elementary items share bytes with a reference.

One rule covers group MOVEs, REDEFINES (item and 01 level) and the shared record area of an FD:
a reference touches every elementary item whose bytes overlap the reference's bytes, over all
OCCURS occurrences (subscripts are not evaluated statically).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from verifier.cobol.datadiv import DataItem
from verifier.cobol.syntax import Program

MAX_RANGES = 4096
Range = tuple[int, int]


def storage_key(prog: Program, root: DataItem) -> str:
    """Records sharing storage get the same key: an FD's records, and REDEFINES chains of 01s."""
    for fd in prog.fds:
        if any(r is root for r in fd.records):
            return "FD:" + fd.name
    by_name = {r.name.upper(): r for r in prog.working_storage + prog.local_storage + prog.linkage}
    cur = root
    seen: set[str] = set()
    while cur.redefines is not None and cur.redefines.upper() in by_name and cur.name not in seen:
        seen.add(cur.name)
        cur = by_name[cur.redefines.upper()]
    return f"{cur.section}:{cur.name}:{cur.line}"


def root_of(item: DataItem) -> DataItem:
    cur = item
    while cur.parent is not None:
        cur = cur.parent
    return cur


def occurs_chain(item: DataItem) -> list[DataItem]:
    """OCCURS items from the outermost ancestor down to `item` itself."""
    out: list[DataItem] = []
    cur: DataItem | None = item
    while cur is not None:
        if cur.occurs:
            out.append(cur)
        cur = cur.parent
    out.reverse()
    return out


def byte_ranges(item: DataItem) -> list[Range]:
    """Every [lo, hi) the item occupies (one per occurrence); a single extent if there are too many."""
    chain = occurs_chain(item)
    width = item.unit_size
    counts = [max(a.occurs or 1, 1) for a in chain]
    total = 1
    for c in counts:
        total *= c
    if total > MAX_RANGES:
        last = item.offset + sum((c - 1) * a.unit_size for a, c in zip(chain, counts, strict=True))
        return [(item.offset, last + width)]
    out: list[Range] = []
    for ks in product(*(range(c) for c in counts)):
        base = item.offset + sum(k * a.unit_size for a, k in zip(chain, ks, strict=True))
        out.append((base, base + width))
    return out


def overlaps(a: list[Range], b: list[Range]) -> bool:
    return any(lo1 < hi2 and lo2 < hi1 for lo1, hi1 in a for lo2, hi2 in b)


def covers(outer: list[Range], inner: list[Range]) -> bool:
    """Every byte of `inner` lies inside `outer`."""
    for lo, hi in inner:
        pos = lo
        for olo, ohi in sorted(outer):
            if olo <= pos < ohi:
                pos = ohi
            if pos >= hi:
                break
        if pos < hi:
            return False
    return True


@dataclass
class Storage:
    """Elementary items of one program grouped by shared storage."""

    prog: Program
    groups: dict[str, list[tuple[DataItem, list[Range]]]] = field(default_factory=dict)
    key_of_root: dict[int, str] = field(default_factory=dict)

    @classmethod
    def build(cls, prog: Program) -> Storage:
        st = cls(prog)
        for root in prog.records():
            key = storage_key(prog, root)
            st.key_of_root[id(root)] = key
            members = st.groups.setdefault(key, [])
            for item in root.walk():
                if item.is_elementary:
                    members.append((item, byte_ranges(item)))
        return st

    def touched(self, item: DataItem) -> list[tuple[DataItem, bool]]:
        """Elementary items sharing bytes with `item`, each with 'fully covered by item'."""
        if item.level in (66, 88):
            return []
        key = self.key_of_root.get(id(root_of(item)))
        if key is None:
            return [(item, True)]
        mine = byte_ranges(item)
        if item.unit_size == 0:
            return [(item, True)]
        out: list[tuple[DataItem, bool]] = []
        for other, ranges in self.groups[key]:
            if other is item:
                out.append((other, True))
            elif overlaps(mine, ranges):
                out.append((other, covers(mine, ranges)))
        return out
