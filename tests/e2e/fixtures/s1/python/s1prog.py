"""Hand translation of S1PROG (decimals held as ints scaled by 10**scale, never float)."""

from __future__ import annotations

import sys


def tdiv(a: int, b: int) -> int:
    """Integer division truncating toward zero (COBOL truncation)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def tmod(a: int, m: int) -> int:
    """Remainder with the sign of the dividend (high-order truncation keeps the sign)."""
    r = abs(a) % m
    return -r if a < 0 else r


def round_div(n: int, d: int) -> int:
    """n / d rounded half away from zero (COBOL ROUNDED)."""
    q = tdiv(n, d)
    r = n - q * d
    if 2 * abs(r) >= abs(d):
        q += 1 if (n < 0) == (d < 0) else -1
    return q


def split_lines(data: bytes) -> list[str]:
    if not data:
        return []
    parts = data.decode("latin-1").split("\n")
    if data.endswith(b"\n"):
        parts.pop()
    return parts


def deedit(w: str, int_digits: int, scale: int, is_signed: bool) -> int:
    """GnuCOBOL's de-editing of ACCEPTed text into a numeric DISPLAY field (scaled int)."""
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


class S1prog:
    def __init__(self, stdin: bytes) -> None:
        self.ws_a: int = 0  # S9(5)V99 VALUE 0, scale 2
        self.ws_b: int = 0  # 9(3) VALUE 0
        self.ws_r: int = 0  # S9(5)V99 VALUE 0, scale 2
        self.ws_i: int = 0  # 9(2)
        self.return_code: int = 0
        self._lines = split_lines(stdin)
        self._pos = 0
        self._out: list[str] = []

    def accept(self, current: int, window: int, int_digits: int, scale: int, is_signed: bool) -> int:
        if self._pos >= len(self._lines):
            return current  # end of input: the field keeps its value
        line = self._lines[self._pos]
        self._pos += 1
        return deedit(line[:window], int_digits, scale, is_signed)

    def display(self, text: str) -> None:
        self._out.append(text + "\n")

    def main_para(self) -> None:
        self.ws_a = self.accept(self.ws_a, 7, 5, 2, True)
        self.ws_b = self.accept(self.ws_b, 3, 3, 0, False)
        self.calc_para()
        self.ws_i = 1
        while self.ws_i <= 2:
            self.display("I=" + unsigned(self.ws_i, 2, 0))
            self.ws_i += 1
        if self.ws_r > 100 * 100:
            self.display("BIG")
        else:
            self.display("SMALL")
        self.display("R=" + signed(self.ws_r, 5, 2))
        self.return_code = 3

    def calc_para(self) -> None:
        # WS-A * 1.5 + WS-B is exact at scale 3; ROUNDED to scale 2, then 5 integer digits kept
        exact = self.ws_a * 15 + self.ws_b * 1000
        self.ws_r = tmod(round_div(exact, 10), 10_000_000)

    def never_para(self) -> None:
        self.display("NEVER")


def main() -> None:
    prog = S1prog(sys.stdin.buffer.read())
    prog.main_para()
    sys.stdout.buffer.write("".join(prog._out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(prog.return_code)


if __name__ == "__main__":
    main()
