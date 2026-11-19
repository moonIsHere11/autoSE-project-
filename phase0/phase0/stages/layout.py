"""Stage C: data dictionary from `verifier.cobol.datadiv` items (sizes and offsets validated against
GnuCOBOL by the verifier's layout probe; re-checked independently by eval O1).

Field ids are the qualified path from the 01/77 level (`WS-ORDER.WS-TOTAL`), prefixed with
`PROGRAM.` when the workspace holds more than one program (Phase 1's convention). FILLER items
get `FILLER#k` (k-th FILLER under the same parent) so every byte of a record has an entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from phase0.schema import ConditionName, Field_, FieldSection, Provenance, SemanticType
from verifier.cobol.datadiv import DataItem
from verifier.cobol.lexer import NUM, PERIOD, Token
from verifier.cobol.syntax import Program

SECTIONS: dict[str, FieldSection] = {
    "WORKING-STORAGE": "working-storage",
    "LOCAL-STORAGE": "local-storage",
    "LINKAGE": "linkage",
    "FILE": "file",
}


@dataclass
class FieldIndex:
    """DataItem identity -> field_id for one program (items are compared by identity, not name)."""

    prefix: str
    ids: dict[int, str] = field(default_factory=dict)
    items: dict[str, DataItem] = field(default_factory=dict)

    def id_of(self, item: DataItem) -> str | None:
        return self.ids.get(id(item))

    def add(self, item: DataItem, fid: str) -> None:
        self.ids[id(item)] = fid
        self.items[fid] = item


def local_names(items: list[DataItem]) -> list[str]:
    """Sibling names with FILLERs numbered."""
    out: list[str] = []
    fillers = 0
    for it in items:
        if it.is_filler:
            fillers += 1
            out.append(f"FILLER#{fillers}")
        else:
            out.append(it.name.upper())
    return out


def index_program(prog: Program, prefix: str) -> FieldIndex:
    index = FieldIndex(prefix)
    roots = prog.records()
    for root, name in zip(roots, local_names(roots), strict=True):
        _index_item(index, root, prefix + name)
    return index


def _index_item(index: FieldIndex, item: DataItem, fid: str) -> None:
    index.add(item, fid)
    for child, name in zip(item.children, local_names(item.children), strict=True):
        _index_item(index, child, f"{fid}.{name}")


def semantic_type(item: DataItem) -> SemanticType:
    if item.is_group or item.pic is None:
        return SemanticType(kind="group", digits=None, scale=None, signed=None, length=item.unit_size)
    pic = item.pic
    if pic.category == "numeric":
        return SemanticType(kind="decimal", digits=pic.digits, scale=pic.scale, signed=pic.signed, length=None)
    return SemanticType(kind="alphanumeric", digits=None, scale=None, signed=None, length=pic.length)


def section_of(item: DataItem) -> FieldSection | None:
    if item.fd is not None:
        return "file"
    return SECTIONS.get(item.section.upper().replace(" SECTION", ""))


def condition_names(item: DataItem) -> list[ConditionName]:
    out: list[ConditionName] = []
    for c in item.conditions:
        if c.level != 88:
            continue
        values = []
        for lo, hi in c.values_88:
            text = str(lo)
            if hi is not None:
                text += " THRU " + str(hi)
            values.append(text)
        out.append(ConditionName(name=c.name.upper(), values=values))
    return out


def parent_id(index: FieldIndex, item: DataItem) -> str | None:
    if item.parent is None:
        return None
    return index.id_of(item.parent)


def redefines_id(index: FieldIndex, item: DataItem, roots: list[DataItem]) -> str | None:
    """REDEFINES names a sibling (or, at level 01, another record)."""
    if item.redefines is None:
        return None
    siblings = roots
    if item.parent is not None:
        siblings = item.parent.children
    for other in siblings:
        if other is not item and other.name.upper() == item.redefines.upper():
            return index.id_of(other)
    return None


def entry_end_lines(tokens: list[Token]) -> dict[tuple[str, int], int]:
    """(file, line) of each data entry's level number -> line of the period that ends the entry."""
    out: dict[tuple[str, int], int] = {}
    start: Token | None = None
    prev_period = True
    for t in tokens:
        if start is None and prev_period and t.kind == NUM and t.text.isdigit():
            start = t
        elif start is not None and t.kind == PERIOD:
            out[(start.file, start.line)] = t.line
            start = None
        prev_period = t.kind == PERIOD
    return out


def optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def field_record(index: FieldIndex, item: DataItem, prog: Program, ends: dict[tuple[str, int], int]) -> Field_:
    pic_text: str | None = None
    if item.pic is not None:
        pic_text = item.pic.raw
    category = "group"
    if item.pic is not None:
        category = item.pic.category
    fid = index.id_of(item)
    assert fid is not None
    return Field_(
        field_id=fid,
        level=item.level,
        parent=parent_id(index, item),
        pic=pic_text,
        usage=item.usage,
        semantic_type=semantic_type(item),
        occurs=item.occurs,
        initial_value=optional_text(item.value),
        program=prog.program_id,
        name=item.name.upper(),
        category=category,
        offset=item.offset,
        byte_length=item.unit_size,
        redefines=redefines_id(index, item, prog.records()),
        occurs_depending_on=item.depending_on,
        condition_names=condition_names(item),
        section=section_of(item),
        provenance=Provenance(
            file=item.file,
            start_line=item.line,
            end_line=ends.get((item.file, item.line), item.line),
            extractor="strict",
            confidence=1.0,
        ),
    )


def data_dictionary(prog: Program, index: FieldIndex, tokens: list[Token]) -> list[Field_]:
    ends = entry_end_lines(tokens)
    out: list[Field_] = []
    for root in prog.records():
        for item in root.walk():
            if index.id_of(item) is not None:
                out.append(field_record(index, item, prog, ends))
    return out
