"""Stage F: Phase 1's semantic-hazard scanner (phase1/phase1/cobol/analyzer.py `find_hazards`)
ported onto the strict front end's typed IR. Same rules, same gap ids, so Phase 2 feedback
(`kb_refs`) and the KB stay aligned. Differences from Phase 1 come only from name resolution and
statement boundaries, and are counted by eval (stage F comparison).
"""

from __future__ import annotations

from phase0.schema import Hazard, Severity
from verifier.cobol import ir as I
from verifier.cobol.analysis import parse_ident, written_names
from verifier.cobol.datadiv import DataItem
from verifier.cobol.lexer import NUM
from verifier.cobol.syntax import Program, Statement

ARITH_VERBS = ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE")
PACKED_USAGES = frozenset({"COMP-3", "PACKED-DECIMAL", "COMP", "BINARY", "COMPUTATIONAL"})


def kind_of(item: DataItem) -> str:
    if item.is_group or item.pic is None:
        return "group"
    if item.pic.category == "numeric":
        return "decimal"
    return "alphanumeric"


def int_digits(item: DataItem) -> int:
    assert item.pic is not None
    return item.pic.integer_digits


def pic(item: DataItem) -> str:
    return item.pic_text()


class HazardScanner:
    def __init__(self) -> None:
        self.out: list[Hazard] = []
        self.seen: set[tuple[str, str]] = set()

    def add(self, gap: str, severity: Severity, line: int, detail: str, fields: list[str]) -> None:
        key = (gap, detail)
        if key in self.seen:
            return
        self.seen.add(key)
        self.out.append(Hazard(gap_id=gap, line=line, detail=detail, fields=fields, severity=severity))

    # ---- MOVE --------------------------------------------------------------------------------
    def move(self, s: I.Move) -> None:
        for dst in s.dsts:
            tf = dst.item
            if isinstance(s.src, I.Lit) and s.src.scale == 0:
                self.literal_move(s.loc.line, s.src.text, len(s.src.digits), tf)
            elif isinstance(s.src, I.Ref):
                self.field_move(s.loc.line, s.src.item, tf, source_length(s.src))

    def literal_move(self, line: int, text: str, digits: int, tf: DataItem) -> None:
        if kind_of(tf) != "decimal":
            return
        if digits > int_digits(tf):
            self.add("G-TRUNCATE", "high", line,
                     f"literal {text} has more integer digits than {tf.name} PIC {pic(tf)}: high-order digits are dropped",
                     [tf.name])

    def field_move(self, line: int, sf: DataItem, tf: DataItem, src_length: int | None) -> None:
        """`src_length` is the sending length; None when a reference modification makes it variable."""
        sk, tk = kind_of(sf), kind_of(tf)
        names = [sf.name, tf.name]
        if sk == "group" and tk == "group":
            self.add("G-GROUPMOVE", "medium", line, f"group MOVE {sf.name} -> {tf.name} copies raw bytes, not field by field", names)
        elif sk == "decimal" and tk == "decimal":
            assert sf.pic is not None and tf.pic is not None
            if int_digits(sf) > int_digits(tf):
                self.add("G-TRUNCATE", "high", line,
                         f"MOVE {sf.name} (PIC {pic(sf)}) -> {tf.name} (PIC {pic(tf)}): high-order digits silently truncated", names)
            if max(sf.pic.scale, 0) > max(tf.pic.scale, 0):
                self.add("G-TRUNCATE", "medium", line,
                         f"MOVE {sf.name} -> {tf.name}: {sf.pic.scale} -> {tf.pic.scale} decimals, fraction truncated not rounded", names)
            if sf.pic.signed and not tf.pic.signed:
                self.add("G-SIGN", "high", line, f"MOVE {sf.name} (signed) -> {tf.name} (unsigned): sign is lost, magnitude stored", names)
        elif {sk, tk} == {"decimal", "alphanumeric"}:
            num = sf.name
            if sk != "decimal":
                num = tf.name
            self.add("G-NUMALPHA", "medium", line,
                     f"MOVE between numeric {num} and alphanumeric field: implicit conversion/padding rules apply", names)
        elif sk == "alphanumeric" and tk == "alphanumeric":
            assert tf.pic is not None
            if src_length is not None and src_length > tf.pic.length:
                self.add("G-TRUNCATE", "medium", line,
                         f"MOVE {sf.name} (X({src_length})) -> {tf.name} (X({tf.pic.length})): right-truncated", names)

    # ---- arithmetic --------------------------------------------------------------------------
    def arith(self, verb: str, line: int, targets: list[tuple[DataItem, bool]], sized: bool) -> None:
        for tf, rounded in targets:
            if kind_of(tf) != "decimal":
                continue
            assert tf.pic is not None
            if not sized:
                sev: Severity = "medium"
                if verb in ("MULTIPLY", "COMPUTE"):
                    sev = "high"
                self.add("G-OVERFLOW", sev, line,
                         f"{verb} into {tf.name} PIC {pic(tf)} ({tf.pic.digits} digits) without ON SIZE ERROR: overflow is silently truncated (BigDecimal would keep all digits)",
                         [tf.name])
            if rounded:
                self.add("G-ROUNDING", "medium", line,
                         f"{verb} ... {tf.name} ROUNDED: COBOL rounds half away from zero; Java defaults (HALF_EVEN / truncation) differ",
                         [tf.name])
            elif verb in ("COMPUTE", "DIVIDE", "MULTIPLY"):
                self.add("G-TRUNCATE", "medium", line,
                         f"{verb} into {tf.name} ({tf.pic.scale} decimals) without ROUNDED: extra decimals truncated, not rounded",
                         [tf.name])
        if verb == "DIVIDE" and not sized:
            self.add("G-DIVZERO", "medium", line,
                     "DIVIDE without ON SIZE ERROR: divide-by-zero leaves target unchanged in COBOL (Java throws)", [])

    def ir_stmt(self, s: I.Stmt) -> None:
        if isinstance(s, I.Move):
            self.move(s)
        elif isinstance(s, I.ArithOp | I.ArithAssign):
            if s.verb in ARITH_VERBS:
                self.arith(s.verb, s.loc.line, [(t.ref.item, t.rounded) for t in s.targets], s.handler)
        elif isinstance(s, I.DivRem):
            targets = [(s.quotient.ref.item, s.quotient.rounded), (s.remainder.item, False)]
            self.arith("DIVIDE", s.loc.line, targets, s.handler)

    def syntax_move(self, prog: Program, st: Statement) -> None:
        """MOVE inside a statement the IR could not lower (e.g. an EVALUATE on an undeclared register)."""
        toks = st.tokens
        ups = [t.up for t in toks]
        if "TO" not in ups or len(toks) < 4:
            return
        k = ups.index("TO")
        targets: list[DataItem] = []
        j = k + 1
        while j < len(toks):
            ident = parse_ident(toks, j)
            if ident is None:
                j += 1
                continue
            item = prog.resolve(ident.name, ident.qualifiers)
            if item is not None:
                targets.append(item)
            j = ident.end
        src_tok = toks[1]
        if src_tok.kind == NUM and k == 2 and "." not in src_tok.text:
            for tf in targets:
                self.literal_move(st.line, src_tok.text, len(src_tok.text.lstrip("+-")), tf)
            return
        ident = parse_ident(toks, 1)
        sf = None
        if ident is not None and ident.end == k:
            sf = prog.resolve(ident.name, ident.qualifiers)
        if sf is None or ident is None:
            return
        length: int | None = sf.unit_size
        if sf.pic is not None:
            length = sf.pic.length
        if ident.refmod:
            length = None
        for tf in targets:
            self.field_move(st.line, sf, tf, length)

    def syntax_stmt(self, prog: Program, st: Statement) -> None:
        """MOVE and arithmetic inside a statement the IR could not lower (e.g. COMPUTE with FUNCTION)."""
        if st.verb == "MOVE":
            self.syntax_move(prog, st)
            return
        if st.verb not in ARITH_VERBS:
            return
        ups = {t.up for t in st.tokens} | {b.kind.upper() for b in st.branches}
        sized = "SIZE" in ups or "SIZE_ERROR" in ups or "NOT_SIZE_ERROR" in ups
        targets: list[tuple[DataItem, bool]] = []
        for name in written_names(prog, st):
            for item in prog.find_items(name):
                targets.append((item, "ROUNDED" in ups))
        self.arith(st.verb, st.line, targets, sized)


def source_length(ref: I.Ref) -> int | None:
    """Sending length of a MOVE source: the PIC length, a literal reference-modification length, or
    None when the reference modification has a variable length (truncation then is not certain)."""
    item = ref.item
    full = item.unit_size
    if item.pic is not None:
        full = item.pic.length
    if ref.refmod is None:
        return full
    start, length = ref.refmod
    if length is None:
        if isinstance(start, I.Lit):
            return full - start.value + 1
        return None
    if isinstance(length, I.Lit):
        return length.value
    return None


def paragraph_hazards(prog: Program, body: list[I.Stmt], syntax: dict[tuple[str, int, str], Statement]) -> list[Hazard]:
    scan = HazardScanner()
    for top in body:
        for s in top.walk():
            if isinstance(s, I.Unsupported):
                st = syntax.get((s.loc.file, s.loc.line, s.verb))
                if st is not None:
                    for sub in st.walk():
                        scan.syntax_stmt(prog, sub)
                continue
            scan.ir_stmt(s)
    return scan.out


def unit_level_hazards(goes_to: list[str], gotos_line: int, falls_to: str | None, end_line: int,
                       start_line: int, touched: list[DataItem]) -> list[Hazard]:
    out: list[Hazard] = []
    if goes_to:
        out.append(Hazard(gap_id="G-GOTO", line=gotos_line, severity="high",
                          detail="GO TO " + ",".join(goes_to[:3]) + ": unstructured control flow, cannot map to a function cleanly"))
    if falls_to is not None:
        out.append(Hazard(gap_id="G-FALLTHROUGH", line=end_line, severity="low",
                          detail=f"control falls through into {falls_to}: translating alone changes behaviour unless the caller PERFORMs THRU"))
    packed = sorted({i.name for i in touched if i.usage in PACKED_USAGES})
    if packed:
        out.append(Hazard(gap_id="G-PACKED", line=start_line, severity="low", fields=packed[:6],
                          detail="binary/packed (COMP/COMP-3) fields: " + ",".join(packed[:4]) + " - same value semantics, different byte layout"))
    return out
