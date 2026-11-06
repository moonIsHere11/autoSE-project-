"""Static facts about a parsed program, used by T1 input generation and diagnosis.

* scope: out-of-scope features (EXEC SQL/CICS, indexed/relative files, SORT/MERGE, ...)
* non-determinism: CURRENT-DATE, ACCEPT FROM DATE/TIME, RANDOM
* input channels: ACCEPT targets (stdin / command line / environment), input and output files
* literal seeds from conditions, EVALUATE/WHEN and 88-levels
* DISPLAY operand layouts (to decode stdout bytes back into field values)
* syntactic write sets per statement (for localisation)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from verifier.cobol.datadiv import DataItem, binary_bytes
from verifier.cobol.lexer import HEX, NUM, STR, WORD, Token
from verifier.cobol.syntax import FileControl, FileDescription, Program, Statement

OUT_OF_SCOPE_PREFIXES = {
    "EXEC SQL": "EXEC SQL",
    "EXEC CICS": "EXEC CICS",
    "INDEXED file": "indexed files",
    "RELATIVE file": "relative files",
    "SORT/MERGE": "SORT/MERGE",
    "SCREEN SECTION": "SCREEN SECTION",
    "REPORT SECTION": "REPORT WRITER",
    "REPORT WRITER": "REPORT WRITER",
}


def out_of_scope(prog: Program) -> list[str]:
    reasons: list[str] = []
    for feat in prog.features:
        for prefix, label in OUT_OF_SCOPE_PREFIXES.items():
            if feat.startswith(prefix) and f"uses {label}" not in reasons:
                reasons.append(f"uses {label}")
    if any(s.organization not in ("SEQUENTIAL", "LINE SEQUENTIAL") for s in prog.selects):
        orgs = sorted({s.organization for s in prog.selects} - {"SEQUENTIAL", "LINE SEQUENTIAL"})
        for o in orgs:
            label = f"uses {o.lower()} files"
            if label not in reasons and f"uses {o.lower().split()[0]} files" not in reasons:
                reasons.append(label)
    return reasons


def nondeterminism(prog: Program) -> list[str]:
    found: list[str] = []
    for st in prog.walk_statements():
        toks = st.tokens
        ups = [t.up for t in toks]
        for i, u in enumerate(ups):
            if u == "FUNCTION" and i + 1 < len(ups) and ups[i + 1] in ("CURRENT-DATE", "RANDOM"):
                found.append(f"FUNCTION {ups[i + 1]} (line {st.line})")
        if st.verb == "ACCEPT" and "FROM" in ups:
            src = ups[ups.index("FROM") + 1] if ups.index("FROM") + 1 < len(ups) else ""
            if src in ("DATE", "TIME", "DAY", "DAY-OF-WEEK"):
                found.append(f"ACCEPT FROM {src} (line {st.line})")
    return found


# ---------------------------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------------------------
@dataclass
class Ident:
    name: str
    qualifiers: list[str]
    subscripts: list[Token]
    refmod: bool
    start: int
    end: int  # index after the identifier


def parse_ident(toks: list[Token], i: int) -> Ident | None:
    if i >= len(toks) or toks[i].kind != WORD:
        return None
    name = toks[i].up
    j = i + 1
    quals: list[str] = []
    while j + 1 < len(toks) and toks[j].is_word("OF", "IN") and toks[j + 1].kind == WORD:
        quals.append(toks[j + 1].up)
        j += 2
    subs: list[Token] = []
    refmod = False
    while j < len(toks) and toks[j].text == "(":
        depth = 0
        while j < len(toks):
            t = toks[j]
            if t.text == "(":
                depth += 1
            elif t.text == ")":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            elif t.text == ":":
                refmod = True
            subs.append(t)
            j += 1
    return Ident(name, quals, subs, refmod, i, j)


def resolve_ident(prog: Program, ident: Ident) -> DataItem | None:
    return prog.resolve(ident.name, ident.qualifiers)


# ---------------------------------------------------------------------------------------------
# loops / reachability
# ---------------------------------------------------------------------------------------------
def _perform_targets(prog: Program, st: Statement) -> list[str]:
    names = [p.name for p in prog.paragraphs]
    toks = st.tokens[1:]
    if not toks or st.branches:
        return []
    first = toks[0].up
    last = first
    for k, t in enumerate(toks):
        if t.is_word("THRU", "THROUGH") and k + 1 < len(toks):
            last = toks[k + 1].up
    if first in prog.sections:
        return [p.name for p in prog.paragraphs if p.section == first]
    if first in names and last in names:
        a, b = names.index(first), names.index(last)
        return names[a : b + 1]
    return [first] if first in names else []


def _is_looping_perform(st: Statement) -> bool:
    ups = [t.up for t in st.tokens]
    return any(u in ("UNTIL", "VARYING", "TIMES") for u in ups)


def loop_reachable_paragraphs(prog: Program) -> set[str]:
    """Paragraphs that may execute more than once (performed from a loop)."""
    looped: set[str] = set()
    changed = True
    while changed:
        changed = False
        for para in prog.paragraphs:
            for st, in_loop in _walk_with_loop(para.statements, para.name in looped):
                if st.verb != "PERFORM" or st.branches:
                    continue
                if in_loop or _is_looping_perform(st):
                    for t in _perform_targets(prog, st):
                        if t not in looped:
                            looped.add(t)
                            changed = True
    return looped


def _walk_with_loop(stmts: list[Statement], in_loop: bool) -> list[tuple[Statement, bool]]:
    out: list[tuple[Statement, bool]] = []
    for st in stmts:
        out.append((st, in_loop))
        inner = in_loop or (st.verb == "PERFORM" and bool(st.branches) and _is_looping_perform(st))
        for b in st.branches:
            out.extend(_walk_with_loop(b.body, inner))
    return out


# ---------------------------------------------------------------------------------------------
# channels
# ---------------------------------------------------------------------------------------------
@dataclass
class AcceptSite:
    target: str
    item: DataItem | None
    source: str  # stdin | date | time | day | dow | cmdline | argument | env | other
    env_name: str | None
    in_loop: bool
    paragraph: str
    line: int
    file: str


@dataclass
class FileChannel:
    select: FileControl
    fd: FileDescription | None
    modes: set[str]
    path: str | None
    dynamic: bool

    @property
    def is_input(self) -> bool:
        return bool(self.modes & {"INPUT", "I-O", "EXTEND"})

    @property
    def is_output(self) -> bool:
        return bool(self.modes & {"OUTPUT", "I-O", "EXTEND"})


@dataclass
class Channels:
    accepts: list[AcceptSite] = field(default_factory=list)
    files: list[FileChannel] = field(default_factory=list)

    @property
    def stdin(self) -> list[AcceptSite]:
        return [a for a in self.accepts if a.source == "stdin"]

    @property
    def input_files(self) -> list[FileChannel]:
        return [f for f in self.files if f.is_input]

    @property
    def output_files(self) -> list[FileChannel]:
        return [f for f in self.files if f.is_output]

    def summary(self) -> dict[str, object]:
        return {
            "stdin_accepts": [
                {"field": a.target, "pic": a.item.pic_text() if a.item else None, "in_loop": a.in_loop,
                 "line": a.line}
                for a in self.stdin
            ],
            "other_accepts": [{"field": a.target, "from": a.source, "line": a.line}
                              for a in self.accepts if a.source != "stdin"],
            "files": [{"select": f.select.name, "path": f.path, "organization": f.select.organization,
                       "modes": sorted(f.modes), "record_size": f.fd.record_size if f.fd else None,
                       "dynamic": f.dynamic} for f in self.files],
        }


_ACCEPT_SOURCES = {
    "DATE": "date", "TIME": "time", "DAY": "day", "DAY-OF-WEEK": "dow",
    "COMMAND-LINE": "cmdline", "ARGUMENT-VALUE": "argument", "ARGUMENT-NUMBER": "argument",
    "ENVIRONMENT": "env", "ENVIRONMENT-VALUE": "env", "CONSOLE": "stdin", "SYSIN": "stdin",
    "STDIN": "stdin", "KEYBOARD": "stdin",
}


def file_path_for(sel: FileControl) -> tuple[str | None, bool]:
    if sel.assign_kind == "literal":
        return sel.assign, False
    if sel.assign_kind == "name":
        return sel.assign, False
    return None, True


def channels(prog: Program) -> Channels:
    ch = Channels()
    looped = loop_reachable_paragraphs(prog)
    modes: dict[str, set[str]] = {}
    for para in prog.paragraphs:
        for st, in_loop in _walk_with_loop(para.statements, para.name in looped):
            if st.verb == "ACCEPT":
                ident = parse_ident(st.tokens, 1)
                if ident is None:
                    continue
                ups = [t.up for t in st.tokens]
                source, env_name = "stdin", None
                if "FROM" in ups:
                    k = ups.index("FROM")
                    src = ups[k + 1] if k + 1 < len(ups) else ""
                    source = _ACCEPT_SOURCES.get(src, "other")
                    if source == "env" and k + 2 < len(st.tokens):
                        nt = st.tokens[k + 2]
                        env_name = nt.value if nt.kind == STR else nt.text
                ch.accepts.append(AcceptSite(ident.name, resolve_ident(prog, ident), source, env_name,
                                             in_loop, para.name, st.line, st.file))
            elif st.verb == "OPEN":
                mode = None
                for t in st.tokens[1:]:
                    if t.is_word("INPUT", "OUTPUT", "EXTEND", "I-O"):
                        mode = t.up
                    elif t.kind == WORD and mode and t.up not in ("WITH", "LOCK", "NO", "REWIND", "SHARING", "ALL", "OTHER", "READ", "ONLY"):
                        modes.setdefault(t.up, set()).add(mode)
    for sel in prog.selects:
        path, dynamic = file_path_for(sel)
        ch.files.append(FileChannel(sel, prog.fd(sel.name), modes.get(sel.name, set()), path, dynamic))
    return ch


# ---------------------------------------------------------------------------------------------
# literal seeds
# ---------------------------------------------------------------------------------------------
_REL_WORDS = {"=", ">", "<", ">=", "<=", "<>", "EQUAL", "GREATER", "LESS", "IS", "NOT", "THAN", "TO", "OR", "EQUALS"}


@dataclass(frozen=True)
class LiteralSeed:
    field: str
    value: str  # numeric text or string value
    kind: str  # num | str


def literal_seeds(prog: Program) -> list[LiteralSeed]:
    seeds: list[LiteralSeed] = []

    def add(name: str, lit: Token) -> None:
        if lit.kind == NUM:
            seeds.append(LiteralSeed(name, lit.text, "num"))
        elif lit.kind in (STR, HEX):
            seeds.append(LiteralSeed(name, lit.value, "str"))

    def scan_condition(toks: list[Token]) -> None:
        last_ident: str | None = None
        pending_lit: Token | None = None
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.kind == WORD and t.up not in _REL_WORDS and t.up not in ("AND", "OR", "NOT"):
                ident = parse_ident(toks, i)
                if ident and prog.resolve(ident.name, ident.qualifiers):
                    last_ident = ident.name
                    if pending_lit is not None:
                        add(ident.name, pending_lit)
                        pending_lit = None
                    i = ident.end
                    continue
            if t.kind in (NUM, STR, HEX):
                if last_ident:
                    add(last_ident, t)
                else:
                    pending_lit = t
            if t.is_word("AND", "OR") and i + 1 < len(toks) and toks[i + 1].kind == WORD and prog.resolve(toks[i + 1].up):
                last_ident = None
            i += 1

    for st in prog.walk_statements():
        if st.verb in ("IF", "PERFORM", "SEARCH"):
            scan_condition(st.tokens[1:])
        for b in st.branches:
            if b.kind == "when" and st.verb == "SEARCH":
                scan_condition(b.tokens)
        if st.verb == "EVALUATE":
            subjects = _evaluate_subjects(prog, st)
            for b in st.branches:
                if b.kind != "when":
                    continue
                objs = _split_also([t for t in b.tokens if not t.is_word("WHEN")])
                for idx, obj in enumerate(objs):
                    subj = subjects[idx] if idx < len(subjects) else None
                    if subj:
                        for t in obj:
                            if t.kind in (NUM, STR, HEX):
                                add(subj, t)
                    else:
                        scan_condition(obj)
    for item in prog.all_items():
        for cond in item.conditions:
            for lo, hi in cond.values_88:
                for v in (lo, hi):
                    if v is None:
                        continue
                    if v.kind == "num":
                        seeds.append(LiteralSeed(item.name, v.text, "num"))
                    elif v.kind == "str":
                        seeds.append(LiteralSeed(item.name, v.text, "str"))
    uniq: list[LiteralSeed] = []
    for s in seeds:
        if s not in uniq:
            uniq.append(s)
    return uniq


def _split_also(toks: list[Token]) -> list[list[Token]]:
    parts: list[list[Token]] = [[]]
    for t in toks:
        if t.is_word("ALSO"):
            parts.append([])
        else:
            parts[-1].append(t)
    return parts


def _evaluate_subjects(prog: Program, st: Statement) -> list[str | None]:
    out: list[str | None] = []
    for part in _split_also(st.tokens[1:]):
        ident = parse_ident(part, 0) if part else None
        if ident and ident.end == len(part) and prog.resolve(ident.name, ident.qualifiers):
            out.append(ident.name)
        else:
            out.append(None)
    return out


# ---------------------------------------------------------------------------------------------
# DISPLAY layouts
# ---------------------------------------------------------------------------------------------
@dataclass
class DisplayOperand:
    kind: str  # literal | item | function | figurative | unknown
    text: str
    item: DataItem | None = None
    length: int | None = None


@dataclass
class DisplaySite:
    line: int
    file: str
    operands: list[DisplayOperand]
    upon: str | None
    no_advancing: bool

    @property
    def fixed_length(self) -> int | None:
        total = 0
        for op in self.operands:
            if op.length is None:
                return None
            total += op.length
        return total


def display_length(item: DataItem) -> int | None:
    """Characters produced by DISPLAY of an elementary item (spike S6, pretty-display)."""
    if item.children:
        return item.size
    p = item.pic
    if p is None:
        return None
    if p.category != "numeric":
        return p.length if item.usage == "DISPLAY" else None
    if item.usage == "COMP-5":
        cap = len(str(2 ** (8 * binary_bytes(p.digits)) - 1))
        digits = cap
    else:
        digits = p.digits
    n = digits
    if p.scale < 0:
        n += -p.scale  # trailing P positions print as zeros
    elif p.scale > p.digits:
        n += p.scale - p.digits  # leading P positions
    if p.scale > 0:
        n += 1  # decimal point
    if p.signed:
        n += 1
    return n


def display_sites(prog: Program) -> list[DisplaySite]:
    sites = []
    figs = {"SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES", "QUOTE", "QUOTES", "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES"}
    for st in prog.walk_statements():
        if st.verb != "DISPLAY":
            continue
        toks = st.tokens[1:]
        ops: list[DisplayOperand] = []
        upon = None
        no_adv = False
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.is_word("UPON"):
                upon = toks[i + 1].up if i + 1 < len(toks) else None
                i += 2
                continue
            if t.is_word("WITH", "NO", "ADVANCING"):
                no_adv = no_adv or t.is_word("NO", "ADVANCING")
                i += 1
                continue
            if t.kind in (STR, HEX):
                ops.append(DisplayOperand("literal", t.value, length=len(t.value)))
                i += 1
            elif t.kind == NUM:
                ops.append(DisplayOperand("literal", t.text, length=len(t.text.lstrip("+"))))
                i += 1
            elif t.is_word("FUNCTION"):
                j = i + 2
                if j < len(toks) and toks[j].text == "(":
                    depth = 0
                    while j < len(toks):
                        if toks[j].text == "(":
                            depth += 1
                        elif toks[j].text == ")":
                            depth -= 1
                            if depth == 0:
                                j += 1
                                break
                        j += 1
                ops.append(DisplayOperand("function", " ".join(x.text for x in toks[i:j])))
                i = j
            elif t.kind == WORD and t.up in figs:
                ops.append(DisplayOperand("figurative", t.up, length=1))
                i += 1
            elif t.kind == WORD:
                ident = parse_ident(toks, i)
                assert ident is not None
                item = resolve_ident(prog, ident)
                length = None if ident.refmod or item is None else display_length(item)
                ops.append(DisplayOperand("item", " ".join(x.text for x in toks[i:ident.end]), item, length))
                i = ident.end
            else:
                ops.append(DisplayOperand("unknown", t.text))
                i += 1
        sites.append(DisplaySite(st.line, st.file, ops, upon, no_adv))
    return sites


# ---------------------------------------------------------------------------------------------
# write sets
# ---------------------------------------------------------------------------------------------
def written_names(prog: Program, st: Statement) -> list[str]:
    """Data names a statement may write (syntactic; used only for 'likely' localisation)."""
    toks = st.tokens
    ups = [t.up for t in toks]
    v = st.verb

    def idents_after(*keywords: str, stop: tuple[str, ...] = ()) -> list[str]:
        out: list[str] = []
        for k, u in enumerate(ups):
            if u in keywords:
                j = k + 1
                while j < len(toks):
                    if toks[j].kind == WORD and (toks[j].up in stop or toks[j].up in keywords):
                        break
                    if toks[j].is_word("ROUNDED"):
                        j += 1
                        continue
                    ident = parse_ident(toks, j)
                    if ident is None:
                        j += 1
                        continue
                    if prog.resolve(ident.name, ident.qualifiers):
                        out.append(ident.name)
                    j = ident.end
        return out

    if v == "MOVE":
        return idents_after("TO")
    if v == "COMPUTE":
        eq = ups.index("=") if "=" in ups else (ups.index("EQUAL") if "EQUAL" in ups else len(ups))
        res = []
        j = 1
        while j < eq:
            ident = parse_ident(toks, j)
            if ident is None:
                j += 1
                continue
            if prog.resolve(ident.name, ident.qualifiers):
                res.append(ident.name)
            j = ident.end
        return res
    if v in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"):
        if "GIVING" in ups:
            return idents_after("GIVING", "REMAINDER", stop=("REMAINDER",))
        key = {"ADD": "TO", "SUBTRACT": "FROM", "MULTIPLY": "BY", "DIVIDE": "INTO"}[v]
        return idents_after(key)
    if v == "ACCEPT":
        ident = parse_ident(toks, 1)
        return [ident.name] if ident else []
    if v == "INITIALIZE":
        return idents_after("INITIALIZE", stop=("REPLACING", "WITH", "TO", "ALL"))
    if v == "SET":
        names = []
        for name in idents_after("SET", stop=("TO", "UP", "DOWN")):
            cond = prog.condition_names().get(name)
            names.append(cond.parent.name if cond is not None and cond.parent is not None else name)
        return names
    if v in ("STRING", "UNSTRING"):
        return idents_after("INTO", "POINTER", "COUNT", "TALLYING", "DELIMITER")
    if v == "INSPECT":
        if "TALLYING" in ups:
            return idents_after("TALLYING", stop=("FOR",))
        ident = parse_ident(toks, 1)
        return [ident.name] if ident else []
    if v == "READ":
        names = []
        if len(toks) > 1:
            fd = prog.fd(toks[1].up)
            if fd is not None:
                names += [r.name for r in fd.records]
        return names + idents_after("INTO")
    if v == "PERFORM":
        return idents_after("VARYING", "AFTER", stop=("FROM",))
    return []


def item_aliases(prog: Program, name: str) -> set[str]:
    """Names whose storage overlaps `name` (ancestors, descendants, REDEFINES siblings)."""
    item = prog.resolve(name)
    if item is None:
        return {name.upper()}
    out = {item.name}
    cur = item.parent
    while cur is not None:
        out.add(cur.name)
        cur = cur.parent
    root = item
    while root.parent is not None:
        root = root.parent
    lo, hi = item.offset, item.offset + item.size
    for other in root.walk():
        if other.offset < hi and lo < other.offset + other.size:
            out.add(other.name)
    for rec in prog.records():
        if rec is not root and rec.redefines == root.name:
            for other in rec.walk():
                if other.offset < hi and lo < other.offset + other.size:
                    out.add(other.name)
    out.discard("FILLER")
    return out
