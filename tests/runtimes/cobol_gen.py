"""Render a batch of difftest cases as ONE fixed-format COBOL program (amortises cobc cost).

Every case prints lines starting with `#<id> `; ENC cases also WRITE their item, padded to 40
bytes with `*`, as one record of the fixed-length SEQUENTIAL file `ENC.DAT`.
"""

from __future__ import annotations

from tests.runtimes.cases import AlnF, Case, NumF

REC_LEN = 40

# codes = cobolrt Round values
ROUND_TXT = {
    0: [], 1: ["ROUNDED"], 2: ["ROUNDED", "MODE", "IS", "NEAREST-AWAY-FROM-ZERO"],
    3: ["ROUNDED", "MODE", "IS", "AWAY-FROM-ZERO"], 4: ["ROUNDED", "MODE", "IS", "NEAREST-EVEN"],
    5: ["ROUNDED", "MODE", "IS", "NEAREST-TOWARD-ZERO"], 6: ["ROUNDED", "MODE", "IS", "TOWARD-GREATER"],
    7: ["ROUNDED", "MODE", "IS", "TOWARD-LESSER"], 8: ["ROUNDED", "MODE", "IS", "PROHIBITED"],
    9: ["ROUNDED", "MODE", "IS", "TRUNCATION"],
}


def _wrap(tokens: list[str], indent: int = 11) -> list[str]:
    """Fixed format: statement text in columns 12-72."""
    lines: list[str] = []
    cur = " " * indent
    for t in tokens:
        if len(cur) + 1 + len(t) > 72 and cur.strip():
            lines.append(cur)
            cur = " " * (indent + 4)
        cur += ("" if cur.endswith(" ") else " ") + t
    if cur.strip():
        lines.append(cur)
    return lines


def _hexlit(b: bytes) -> str:
    return f'X"{b.hex().upper()}"' if b else "SPACES"


class _Prog:
    def __init__(self) -> None:
        self.ws: list[str] = []
        self.proc: list[str] = []

    def stmt(self, *tokens: str) -> None:
        self.proc += _wrap(list(tokens))


def _names(c: Case) -> list[str]:
    return [f"C{c.name}{chr(ord('A') + i)}" for i in range(len(c.fields))]


def _size_tokens(c: Case, end: str) -> list[str]:
    t: list[str] = []
    if c.size in (1, 3):
        t += ["ON", "SIZE", "ERROR", "DISPLAY", f'"#{c.name} SE"']
    if c.size in (1, 2):
        t += ["NOT", "ON", "SIZE", "ERROR", "DISPLAY", f'"#{c.name} NSE"']
    return [*t, end]


def _round(c: Case) -> list[str]:
    return ROUND_TXT[c.round]


def _expr(rpn: list[str], names: list[str]) -> list[str]:
    stack: list[list[str]] = []
    for t in rpn:
        if t.startswith("$"):
            stack.append([names[int(t[1:])]])
        elif t.startswith("#"):
            stack.append([t[1:]])
        elif t == "~":
            a = stack.pop()
            stack.append(["(", "-", *a, ")"])
        else:
            b = stack.pop()
            a = stack.pop()
            stack.append(["(", *a, t, *b, ")"])
    assert len(stack) == 1
    return stack[0]


def render(cases: list[Case], program_id: str = "RTDIFF") -> tuple[str, bytes]:
    """COBOL source and the stdin bytes for a batch."""
    p = _Prog()
    stdin = b""
    for c in cases:
        names = _names(c)
        for (f, _v), nm in zip(c.fields, names, strict=True):
            if c.op == "ENC" and nm.endswith("A"):
                assert isinstance(f, NumF)
                p.ws.append(f"       01 C{c.name}G.")
                p.ws += _wrap([f"05 {nm}", f.clause() + "."], 11)
                p.ws.append(f'           05 FILLER PIC X({REC_LEN - f.nbytes}) VALUE ALL "*".')
            else:
                p.ws += _wrap([f"01 {nm}", f.clause() + "."], 7)
        # initial values
        for (f, v), nm in zip(c.fields, names, strict=True):
            if isinstance(f, NumF):
                assert isinstance(v, int)
                p.stmt("MOVE", f.literal(v), "TO", nm)
            else:
                assert isinstance(v, bytes)
                p.stmt("MOVE", _hexlit(v), "TO", nm)
        _emit_case(p, c, names)
        for line in c.stdin:
            if line is not None:
                stdin += line + b"\n"
    head = [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {program_id}.",
        "       ENVIRONMENT DIVISION.",
        "       INPUT-OUTPUT SECTION.",
        "       FILE-CONTROL.",
        '           SELECT ENC-FILE ASSIGN TO "ENC.DAT"',
        "               ORGANIZATION IS SEQUENTIAL.",
        "       DATA DIVISION.",
        "       FILE SECTION.",
        "       FD ENC-FILE.",
        f"       01 ENC-REC PIC X({REC_LEN}).",
        "       WORKING-STORAGE SECTION.",
    ]
    proc = ["       PROCEDURE DIVISION.", "           OPEN OUTPUT ENC-FILE.", *p.proc,
            "           CLOSE ENC-FILE.", "           STOP RUN."]
    return "\n".join(head + p.ws + proc) + "\n", stdin


def _show(p: _Prog, c: Case, tag: str, nm: str) -> None:
    p.stmt("DISPLAY", f'"#{c.name} {tag} "', nm, '"|"', f"FUNCTION HEX-OF({nm})")


def _emit_case(p: _Prog, c: Case, n: list[str]) -> None:
    op = c.op
    rnd = _round(c)
    if op == "MOVE":
        p.stmt("MOVE", n[0], "TO", n[1])
        _show(p, c, "R1", n[1])
    elif op == "MOVEL":
        p.stmt("MOVE", c.extra[0], "TO", n[0])
        _show(p, c, "R1", n[0])
    elif op == "DISP":
        _show(p, c, "R1", n[0])
    elif op == "ENC":
        p.stmt("WRITE", "ENC-REC", "FROM", f"C{c.name}G")
        _show(p, c, "R1", n[0])
    elif op in ("ADD", "SUB", "MUL", "DIVI"):
        verb, prep, end = {"ADD": ("ADD", "TO", "END-ADD"), "SUB": ("SUBTRACT", "FROM", "END-SUBTRACT"),
                           "MUL": ("MULTIPLY", "BY", "END-MULTIPLY"), "DIVI": ("DIVIDE", "INTO", "END-DIVIDE")}[op]
        p.stmt(verb, n[0], prep, n[1], *rnd, *_size_tokens(c, end))
        _show(p, c, "R1", n[1])
    elif op in ("ADDG", "SUBG", "MULG", "DIVIG", "DIVBG"):
        verb, prep, end = {"ADDG": ("ADD", "TO", "END-ADD"), "SUBG": ("SUBTRACT", "FROM", "END-SUBTRACT"),
                           "MULG": ("MULTIPLY", "BY", "END-MULTIPLY"), "DIVIG": ("DIVIDE", "INTO", "END-DIVIDE"),
                           "DIVBG": ("DIVIDE", "BY", "END-DIVIDE")}[op]
        p.stmt(verb, n[0], prep, n[1], "GIVING", n[2], *rnd, *_size_tokens(c, end))
        _show(p, c, "R1", n[2])
    elif op in ("DIVBR", "DIVIR"):
        prep = "BY" if op == "DIVBR" else "INTO"
        p.stmt("DIVIDE", n[0], prep, n[1], "GIVING", n[2], *rnd, "REMAINDER", n[3],
               *_size_tokens(c, "END-DIVIDE"))
        _show(p, c, "R1", n[2])
        _show(p, c, "R2", n[3])
    elif op == "COMP":
        p.stmt("COMPUTE", n[0], *rnd, "=", *_expr(c.extra, n), *_size_tokens(c, "END-COMPUTE"))
        _show(p, c, "R1", n[0])
    elif op in ("NX", "XN", "XX"):
        p.stmt("MOVE", n[0], "TO", n[1])
        _show(p, c, "R1", n[1])
    elif op == "XL":
        p.stmt("MOVE", _hexlit(bytes.fromhex(c.extra[0])), "TO", n[0])
        _show(p, c, "R1", n[0])
    elif op in ("CMP", "XCMP"):
        p.stmt("IF", n[0], "<", n[1], "DISPLAY", f'"#{c.name} LT"', "ELSE", "IF", n[0], "=", n[1],
               "DISPLAY", f'"#{c.name} EQ"', "ELSE", "DISPLAY", f'"#{c.name} GT"', "END-IF", "END-IF")
    elif op in ("ACC", "ACCX"):
        p.stmt("ACCEPT", n[0])
        _show(p, c, "R1", n[0])
    else:
        raise ValueError(op)


def describe(c: Case) -> str:
    """One-line human description of a case (for failure reports)."""
    parts = []
    for (f, v), nm in zip(c.fields, _names(c), strict=True):
        if isinstance(f, NumF):
            assert isinstance(v, int)
            parts.append(f"{nm} {f.clause()} = {f.literal(v)}")
        else:
            assert isinstance(f, AlnF) and isinstance(v, bytes)
            parts.append(f"{nm} {f.clause()} = {v!r}")
    p = _Prog()
    _emit_case(p, c, _names(c))
    stmt = " ".join(" ".join(x.split()) for x in p.proc[: max(1, len(p.proc) - 2)])
    return f"[{c.op}] " + "; ".join(parts) + f" :: {stmt}" + (f" stdin={c.stdin!r}" if c.stdin else "")
