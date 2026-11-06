"""Hand translation of TEMPCONV using decimal.Decimal for every numeric field (never float).

COBOL arithmetic is reproduced exactly: an intermediate quotient is truncated 38 digits beyond the
operands' scale (as GnuCOBOL does), the final store either truncates or rounds half away from
zero, and high-order digits are dropped without ON SIZE ERROR.
"""

from __future__ import annotations

import sys
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, getcontext, localcontext

# additions/multiplications must stay exact (a 38-digit quotient plus an integer part)
getcontext().prec = 200

K_OFFSET = Decimal("273.15")
NINE_FIFTHS = Decimal("1.8")
THIRTY_TWO = Decimal(32)
ZERO = Decimal(0)


def _scale(d: Decimal) -> int:
    exp = d.as_tuple().exponent
    return -exp if isinstance(exp, int) else 0


def div(a: Decimal, b: Decimal) -> Decimal:
    """COBOL division: quotient truncated toward zero, 38 digits beyond the operands' scale."""
    scale = 38 + max(0, _scale(a) - _scale(b))
    with localcontext() as ctx:
        ctx.prec = 200
        ctx.rounding = ROUND_DOWN
        return (a / b).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_DOWN)


def store(v: Decimal, int_digits: int, scale: int, is_signed: bool, rounded: bool) -> Decimal:
    """Store a result in a PIC: ROUNDED (half away from zero) or truncation, then high-order truncation."""
    with localcontext() as ctx:
        ctx.prec = 200
        q = Decimal(1).scaleb(-scale)
        r = v.quantize(q, rounding=ROUND_HALF_UP if rounded else ROUND_DOWN)
        r = r % (Decimal(10) ** int_digits)  # sign of the dividend, like COBOL truncation
        if not is_signed or r == 0:
            r = abs(r)
        return r.quantize(q)


def size_error(v: Decimal, int_digits: int, scale: int, rounded: bool) -> bool:
    with localcontext() as ctx:
        ctx.prec = 200
        r = v.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP if rounded else ROUND_DOWN)
        return abs(r) >= Decimal(10) ** int_digits


def display(v: Decimal, int_digits: int, scale: int, is_signed: bool) -> str:
    """DISPLAY of a numeric DISPLAY field (signed: leading sign always shown)."""
    r = v.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_DOWN)
    digits = str(abs(int(r.scaleb(scale)))).rjust(int_digits + scale, "0")
    body = digits[: len(digits) - scale] + "." + digits[len(digits) - scale:] if scale > 0 else digits
    if is_signed:
        return ("-" if r < 0 else "+") + body
    return body


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


class Tempconv:
    def __init__(self, stdin: bytes) -> None:
        self.ws_temp: Decimal = ZERO  # S9(2)
        self.ws_mode: int = 0  # 9
        self.ws_celsius: Decimal = Decimal("0.00")  # S9(3)V99
        self.ws_fahr: Decimal = Decimal("0.00")  # S9(3)V99
        self.ws_kelvin: Decimal = Decimal("0.00")  # 9(3)V99
        self.ws_result: Decimal = Decimal("0.0")  # S9(3)V9
        self.ws_result_t: Decimal = Decimal("0.0")  # S9(3)V9
        self.ws_magnitude: Decimal = Decimal("0.0")  # 9(3)V9
        self.ws_thirds: Decimal = Decimal("0.0")  # S9(3)V9
        self.ws_thirds_r: Decimal = Decimal("0.0")  # S9(3)V9
        self.ws_spread: Decimal = Decimal("0.0")  # S9(2)V9
        self.ws_spread_flag: str = "   "  # X(3)
        self.ws_feel: str = " " * 8  # X(8)
        self.return_code: int = 0
        data = stdin.decode("latin-1")
        self._lines = data.split("\n") if data else []
        if data.endswith("\n"):
            self._lines.pop()
        self._out: list[str] = []

    def main_para(self) -> None:
        self.get_input()
        if 1 <= self.ws_mode <= 5:
            self.convert()
            self.classify()
            self.report_out()
        else:
            self.line("UNKNOWN MODE " + str(self.ws_mode) + " FOR " + display(self.ws_temp, 2, 0, True))
            self.return_code = 3

    def get_input(self) -> None:
        self.ws_temp = Decimal(self.accept_numeric(2, 2, 0, True))
        self.ws_mode = self.accept_numeric(1, 1, 0, False)

    def convert(self) -> None:
        t = self.ws_temp
        nine, five = Decimal(9), Decimal(5)
        if self.ws_mode == 1:
            self.ws_celsius = store(t, 3, 2, True, False)
            self.ws_fahr = store(div(t * nine, five) + THIRTY_TWO, 3, 2, True, True)
            self.ws_result = store(div(t * nine, five) + THIRTY_TWO, 3, 1, True, True)
            self.ws_result_t = store(div(t * nine, five) + THIRTY_TWO, 3, 1, True, False)
        elif self.ws_mode == 2:
            self.ws_fahr = store(t, 3, 2, True, False)
            self.ws_celsius = store(div((t - THIRTY_TWO) * five, nine), 3, 2, True, True)
            self.ws_result = store(div((t - THIRTY_TWO) * five, nine), 3, 1, True, True)
            self.ws_result_t = store(div(t - THIRTY_TWO, nine) * five, 3, 1, True, False)
        elif self.ws_mode == 3:
            self.ws_celsius = store(t, 3, 2, True, False)
            self.ws_fahr = store(t * NINE_FIFTHS + THIRTY_TWO, 3, 2, True, True)
            self.ws_result = store(t + K_OFFSET, 3, 1, True, True)
            self.ws_result_t = store(t + K_OFFSET, 3, 1, True, False)
        elif self.ws_mode == 4:
            self.ws_fahr = store(t, 3, 2, True, False)
            self.ws_celsius = store(div(t - THIRTY_TWO, NINE_FIFTHS), 3, 2, True, True)
            self.ws_result = store(div(t - THIRTY_TWO, NINE_FIFTHS) + K_OFFSET, 3, 1, True, True)
            self.ws_result_t = store(div(t - THIRTY_TWO, NINE_FIFTHS) + K_OFFSET, 3, 1, True, False)
        else:
            self.ws_celsius = store(t, 3, 2, True, False)
            self.ws_fahr = store(div(t * nine, five) + THIRTY_TWO, 3, 2, True, True)
            self.ws_result = store(div((self.ws_fahr - THIRTY_TWO) * five, nine), 3, 1, True, True)
            self.ws_result_t = store(div(self.ws_fahr - THIRTY_TWO, nine) * five, 3, 1, True, False)
        self.ws_kelvin = store(self.ws_celsius + K_OFFSET, 3, 2, False, True)
        self.ws_magnitude = store(self.ws_result, 3, 1, False, False)
        self.ws_thirds = store(div(t, Decimal(3)) * Decimal(3), 3, 1, True, False)
        self.ws_thirds_r = store(div(t, Decimal(3)) * Decimal(3), 3, 1, True, True)
        spread = self.ws_fahr - self.ws_celsius
        if size_error(spread, 2, 1, False):
            self.ws_spread_flag = "OVF"
        else:
            self.ws_spread = store(spread, 2, 1, True, False)
            self.ws_spread_flag = "OK "

    def classify(self) -> None:
        c = self.ws_celsius
        if c < -10:
            self.ws_feel = "FREEZING"
        elif c < 0:
            self.ws_feel = "COLD    "
        elif c == 0:
            self.ws_feel = "ZERO    "
        elif c < 20:
            self.ws_feel = "MILD    "
        elif c < 30:
            self.ws_feel = "WARM    "
        else:
            self.ws_feel = "HOT     "

    def report_out(self) -> None:
        self.line("MODE " + str(self.ws_mode) + " INPUT " + display(self.ws_temp, 2, 0, True))
        self.line("CELSIUS " + display(self.ws_celsius, 3, 2, True) + " FAHRENHEIT " + display(self.ws_fahr, 3, 2, True)
                  + " KELVIN " + display(self.ws_kelvin, 3, 2, False))
        self.line("RESULT " + display(self.ws_result, 3, 1, True) + " TRUNCATED " + display(self.ws_result_t, 3, 1, True)
                  + " MAGNITUDE " + display(self.ws_magnitude, 3, 1, False))
        self.line("THIRDS " + display(self.ws_thirds, 3, 1, True) + " ROUNDED " + display(self.ws_thirds_r, 3, 1, True))
        self.line("SPREAD " + display(self.ws_spread, 2, 1, True) + " " + self.ws_spread_flag + " FEEL " + self.ws_feel)

    def line(self, s: str) -> None:
        self._out.append(s + "\n")

    def accept_numeric(self, window: int, int_digits: int, scale: int, is_signed: bool) -> int:
        if not self._lines:
            return 0
        return deedit(self._lines.pop(0)[:window], int_digits, scale, is_signed)


def main() -> None:
    prog = Tempconv(sys.stdin.buffer.read())
    prog.main_para()
    sys.stdout.buffer.write("".join(prog._out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(prog.return_code)


if __name__ == "__main__":
    main()
