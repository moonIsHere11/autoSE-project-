"""Small COBOL-semantics helpers shared by the translation (scaled ints, never float)."""

from __future__ import annotations


def tdiv(a: int, b: int) -> int:
    """Integer division truncating toward zero (COBOL), not Python's floor division."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def tmod(a: int, m: int) -> int:
    """Remainder taking the sign of the dividend."""
    r = abs(a) % abs(m)
    return -r if a < 0 else r


def split_lines(data: bytes) -> list[str]:
    if not data:
        return []
    parts = data.decode("latin-1").split("\n")
    if data.endswith(b"\n"):
        parts.pop()
    return parts


def deedit(w: str, int_digits: int, scale: int, is_signed: bool) -> int:
    """GnuCOBOL de-editing of ACCEPTed text into a numeric DISPLAY field (scaled int)."""
    i, n = 0, len(w)
    while i < n and w[i] == " ":
        i += 1
    neg = False
    if i < n and w[i] in "+-":
        neg = w[i] == "-"
        i += 1
        while i < n and w[i] == " ":
            i += 1
    ip: list[str] = []
    fp: list[str] = []
    dot = False
    while i < n:
        c = w[i]
        if "0" <= c <= "9":
            (fp if dot else ip).append(c)
        elif c == "." and not dot:
            dot = True
        elif c != ",":
            break
        i += 1
    while i < n and w[i] == " ":
        i += 1
    if i < n:
        only_sign = w[i] in "+-" and not w[i + 1:].strip()
        if not only_sign or scale > 0:
            return 0
    if not ip and not fp:
        return 0
    ints = ip[-int_digits:] if len(ip) > int_digits else ip
    v = 0
    for c in ints:
        v = v * 10 + ord(c) - 48
    for k in range(scale):
        v = v * 10 + (ord(fp[k]) - 48 if k < len(fp) else 0)
    return -v if neg and is_signed else v


def unsigned(v: int, int_digits: int, scale: int) -> str:
    s = str(abs(v)).rjust(int_digits + scale, "0")
    return s[: len(s) - scale] + "." + s[len(s) - scale:] if scale > 0 else s


def signed(v: int, int_digits: int, scale: int) -> str:
    return ("-" if v < 0 else "+") + unsigned(v, int_digits, scale)
