"""Syntax tree for a parsed COBOL program (generic statements; the typed IR is in ir.py)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from verifier.cobol.datadiv import DataItem
from verifier.cobol.lexer import Token


@dataclass
class Branch:
    kind: str  # then, else, when, other, body, size_error, not_size_error, at_end, ...
    tokens: list[Token]
    body: list[Statement]


@dataclass
class Statement:
    verb: str
    tokens: list[Token]  # header tokens, starting with the verb
    file: str
    line: int
    end_line: int
    branches: list[Branch] = field(default_factory=list)
    terminated: bool = False  # explicit END-xxx

    def walk(self) -> Iterator[Statement]:
        yield self
        for b in self.branches:
            for s in b.body:
                yield from s.walk()

    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)


@dataclass
class Paragraph:
    name: str
    section: str | None
    file: str
    line: int
    end_line: int
    statements: list[Statement] = field(default_factory=list)
    sentence_starts: list[int] = field(default_factory=list)  # indexes into statements

    def walk(self) -> Iterator[Statement]:
        for s in self.statements:
            yield from s.walk()


@dataclass
class FileControl:
    name: str
    assign: str | None
    assign_kind: str  # literal | name | dataname | none
    organization: str  # LINE SEQUENTIAL | SEQUENTIAL | RECORD SEQUENTIAL | INDEXED | RELATIVE
    access: str
    file_status: str | None
    optional: bool
    line: int
    file: str


@dataclass
class FileDescription:
    name: str
    kind: str  # FD | SD
    records: list[DataItem]
    line: int
    record_varying: bool = False

    @property
    def record_size(self) -> int:
        return max((r.size for r in self.records), default=0)


@dataclass
class Program:
    program_id: str
    source_file: str
    line: int
    selects: list[FileControl] = field(default_factory=list)
    fds: list[FileDescription] = field(default_factory=list)
    working_storage: list[DataItem] = field(default_factory=list)
    local_storage: list[DataItem] = field(default_factory=list)
    linkage: list[DataItem] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    using: list[str] = field(default_factory=list)
    features: dict[str, list[int]] = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)
    special_names: list[str] = field(default_factory=list)

    # --- lookups -------------------------------------------------------------------------
    def records(self) -> list[DataItem]:
        recs: list[DataItem] = []
        for fd in self.fds:
            recs.extend(fd.records)
        return recs + self.working_storage + self.local_storage + self.linkage

    def all_items(self) -> list[DataItem]:
        out: list[DataItem] = []
        for r in self.records():
            out.extend(r.walk())
        return out

    def find_items(self, name: str) -> list[DataItem]:
        up = name.upper()
        return [i for i in self.all_items() if i.name == up]

    def resolve(self, name: str, qualifiers: list[str] | None = None) -> DataItem | None:
        cands = self.find_items(name)
        if qualifiers:
            qs = [q.upper() for q in qualifiers]
            cands = [c for c in cands if all(q in c.path()[1:] for q in qs)]
        return cands[0] if len(cands) == 1 else None  # ambiguous or unknown

    def condition_names(self) -> dict[str, DataItem]:
        out: dict[str, DataItem] = {}
        for item in self.all_items():
            for c in item.conditions:
                if c.level == 88:
                    out[c.name] = c
        return out

    def select(self, name: str) -> FileControl | None:
        for s in self.selects:
            if s.name == name.upper():
                return s
        return None

    def fd(self, name: str) -> FileDescription | None:
        for f in self.fds:
            if f.name == name.upper():
                return f
        return None

    def paragraph(self, name: str) -> Paragraph | None:
        for p in self.paragraphs:
            if p.name == name.upper():
                return p
        return None

    def walk_statements(self) -> Iterator[Statement]:
        for p in self.paragraphs:
            yield from p.walk()

    def add_feature(self, name: str, line: int) -> None:
        self.features.setdefault(name, []).append(line)
