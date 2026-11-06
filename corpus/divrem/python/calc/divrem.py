"""Hand translation of DIVREM. Numerics are ints scaled by 10**scale; divisions truncate toward
zero and remainders take the sign of the dividend (tdiv/tmod), as in COBOL."""

from __future__ import annotations

import sys

from calc.cobolsem import deedit, signed, split_lines, tdiv, tmod, unsigned


class Divrem:
    def __init__(self, stdin: bytes) -> None:
        self.ws_dividend: int = 0  # S9(2)
        self.ws_divisor: int = 0  # 9
        self.ws_quot: int = 0  # S9(2)
        self.ws_rem: int = 0  # S9
        self.ws_quot_r: int = 0  # S9(2)V9, scale 1
        self.ws_rem_r: int = 0  # S9V99, scale 2
        self.ws_ratio: int = 0  # S9V9 VALUE 0, scale 1
        self.ws_ratio_flag: str = " "  # X VALUE SPACE
        self.ws_uquot: int = 77  # 9(2) VALUE 77
        self.ws_acc: int = 120  # S9(3) VALUE 120
        self.ws_check: int = 0  # S9(3)
        self.ws_status: str = "    "  # X(4)
        self.ws_kind: str = " " * 9  # X(9)
        self.ws_div_class: str = " " * 8  # X(8)
        self.ws_gcd_a: int = 0  # 9(2)
        self.ws_gcd_b: int = 0  # 9(2)
        self.ws_gcd_q: int = 0  # 9(2)
        self.ws_gcd_t: int = 0  # 9(2)
        self.ws_steps: int = 0  # 9(2) VALUE 0
        self.return_code: int = 0
        self._lines = split_lines(stdin)
        self._out: list[str] = []

    def main_para(self) -> None:
        self.get_operands()
        self.do_divide()
        self.classify_result()
        self.find_gcd()
        self.show_result()
        self.set_return()

    def get_operands(self) -> None:
        self.ws_dividend = self.accept_numeric(2, 2, 0, True)
        self.ws_divisor = self.accept_numeric(1, 1, 0, False)

    def do_divide(self) -> None:
        if self.ws_divisor == 0:
            self.ws_status = "ZDIV"  # ON SIZE ERROR: targets unchanged
        else:
            q = tdiv(self.ws_dividend, self.ws_divisor)
            self.ws_quot = tmod(q, 100)
            self.ws_rem = tmod(self.ws_dividend - q * self.ws_divisor, 10)
            self.ws_status = "OK  "
        if self.ws_divisor != 0:
            n = self.ws_dividend * 10  # quotient at scale 1
            qt = tdiv(n, self.ws_divisor)  # truncated quotient
            r = tmod(n, self.ws_divisor)
            qr = qt
            if 2 * abs(r) >= self.ws_divisor:
                qr = qt + (-1 if n < 0 else 1)  # ROUNDED: half away from zero
            self.ws_quot_r = tmod(qr, 1000)
            self.ws_rem_r = tmod((n - qt * self.ws_divisor) * 10, 1000)  # uses the truncated quotient
        if self.ws_divisor == 0:
            self.ws_ratio_flag = "Y"
        else:
            n = self.ws_dividend * 10
            q = tdiv(n, self.ws_divisor)
            r = tmod(n, self.ws_divisor)
            if 2 * abs(r) >= self.ws_divisor:
                q = q + (-1 if n < 0 else 1)
            if q >= 100 or q <= -100:
                self.ws_ratio_flag = "Y"
            else:
                self.ws_ratio = q
                self.ws_ratio_flag = "N"
        if self.ws_divisor != 0:  # no SIZE ERROR phrase: a zero divisor leaves the target as is
            self.ws_acc = tmod(tdiv(self.ws_acc, self.ws_divisor), 1000)
        if self.ws_divisor != 0:
            q = tdiv(self.ws_dividend, self.ws_divisor)
            self.ws_uquot = abs(q) % 100  # unsigned target drops the sign
        self.ws_check = tmod(self.ws_quot * self.ws_divisor + self.ws_rem, 1000)

    def classify_result(self) -> None:
        if self.ws_divisor == 0:
            self.ws_kind = "UNDEFINED"
        elif self.ws_rem == 0 and self.ws_dividend < 0:
            self.ws_kind = "NEG-EXACT"
        elif self.ws_rem == 0:
            self.ws_kind = "EXACT    "
        elif self.ws_rem < 0 and 1 <= self.ws_divisor <= 3:
            self.ws_kind = "NEG-SMALL"
        else:
            self.ws_kind = "INEXACT  "
        if self.ws_divisor == 0:
            self.ws_div_class = "NONE    "
        elif 1 <= self.ws_divisor <= 3:
            self.ws_div_class = "LOW-DIV "
        elif self.ws_quot == 0:
            self.ws_div_class = "ZERO-Q  "
        elif -9 <= self.ws_quot <= -1:
            self.ws_div_class = "NEG-Q   "
        else:
            self.ws_div_class = "HIGH-DIV"

    def find_gcd(self) -> None:
        self.ws_gcd_a = abs(self.ws_dividend) % 100
        self.ws_gcd_b = self.ws_divisor
        while self.ws_gcd_b != 0:
            self.ws_gcd_q = (self.ws_gcd_a // self.ws_gcd_b) % 100
            self.ws_gcd_t = (self.ws_gcd_a % self.ws_gcd_b) % 100
            self.ws_gcd_a = self.ws_gcd_b
            self.ws_gcd_b = self.ws_gcd_t
            self.ws_steps = (self.ws_steps + 1) % 100

    def show_result(self) -> None:
        self.line("DIVIDEND " + signed(self.ws_dividend, 2, 0) + " DIVISOR " + unsigned(self.ws_divisor, 1, 0)
                  + " STATUS " + self.ws_status)
        self.line("QUOT " + signed(self.ws_quot, 2, 0) + " REM " + signed(self.ws_rem, 1, 0)
                  + " CHECK " + signed(self.ws_check, 3, 0))
        self.line("QUOT-R " + signed(self.ws_quot_r, 2, 1) + " REM-R " + signed(self.ws_rem_r, 1, 2))
        self.line("RATIO " + signed(self.ws_ratio, 1, 1) + " SIZE " + self.ws_ratio_flag
                  + " UQUOT " + unsigned(self.ws_uquot, 2, 0) + " ACC " + signed(self.ws_acc, 3, 0))
        self.line("KIND " + self.ws_kind + " CLASS " + self.ws_div_class + " GCD " + unsigned(self.ws_gcd_a, 2, 0)
                  + " STEPS " + unsigned(self.ws_steps, 2, 0))

    def set_return(self) -> None:
        if self.ws_divisor == 0:
            self.return_code = 8
        elif self.ws_rem != 0:
            self.return_code = 1
        else:
            self.return_code = 0

    # ------------------------------------------------------------------ I/O helpers
    def line(self, s: str) -> None:
        self._out.append(s + "\n")

    def accept_numeric(self, window: int, int_digits: int, scale: int, is_signed: bool) -> int:
        """ACCEPT into a numeric DISPLAY field (first byte-length characters, de-edited); EOF gives 0."""
        if not self._lines:
            return 0
        return deedit(self._lines.pop(0)[:window], int_digits, scale, is_signed)


def main() -> None:
    prog = Divrem(sys.stdin.buffer.read())
    prog.main_para()
    sys.stdout.buffer.write("".join(prog._out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(prog.return_code)


if __name__ == "__main__":
    main()
