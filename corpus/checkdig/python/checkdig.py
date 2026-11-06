"""Hand translation of CHECKDIG: mod-11 check digits for up to three account numbers."""

from __future__ import annotations

import sys


def split_lines(data: bytes) -> list[str]:
    """stdin lines terminated by '\\n' only (a last line without '\\n' still counts)."""
    if not data:
        return []
    parts = data.decode("latin-1").split("\n")
    if data.endswith(b"\n"):
        parts.pop()
    return parts


def num(v: int, digits: int) -> str:
    """DISPLAY of an unsigned integer DISPLAY field with `digits` digits."""
    return str(abs(v)).rjust(digits, "0")


def pad(s: str, n: int) -> str:
    return s[:n].ljust(n)


class Checkdig:
    def __init__(self, stdin: bytes) -> None:
        self.ws_account: str = " " * 10  # X(10)
        self.ws_acct_no: int = 0  # 9(1) VALUE 0
        self.ws_valid_count: int = 0  # 9(1) VALUE 0
        self.ws_i: int = 0  # 9(2)
        self.ws_weight: int = 0  # 9(2)
        self.ws_digit: int = 0  # 9(1)
        self.ws_given: int = 0  # 9(1)
        self.ws_sum: int = 0  # 9(3)
        self.ws_quot: int = 0  # 9(3)
        self.ws_rem: int = 0  # 9(2)
        self.ws_check: int = 0  # 9(2)
        self.ws_check_d: int = 0  # 9(1)
        self.ws_check_x: str = " "  # X(1)
        self.ws_bad: int = 0  # 9(2)
        self.ws_result: str = " " * 7  # X(7)
        self.return_code: int = 0
        self._lines = split_lines(stdin)
        self._out: list[str] = []

    def main_para(self) -> None:
        for _ in range(3):
            self.check_one()
        self._out.append("VALID ACCOUNTS: " + num(self.ws_valid_count, 1) + "\n")

    def check_one(self) -> None:
        self.ws_acct_no = (self.ws_acct_no + 1) % 10
        self.ws_account = self.accept_alnum(10)
        self.scan_chars()
        if self.ws_bad > 0:
            self._out.append(num(self.ws_acct_no, 1) + " [" + self.ws_account + "] REJECTED: "
                             + num(self.ws_bad, 2) + " NON-DIGIT(S)\n")
        else:
            self.weigh_digits()
            self.derive_check()
            self.report_result()

    def scan_chars(self) -> None:
        self.ws_bad = 0
        self.ws_i = 1
        while not self.ws_i > 10:
            c = self.ws_account[self.ws_i - 1]
            if c < "0" or c > "9":
                self.ws_bad = (self.ws_bad + 1) % 100
            self.ws_i += 1

    def weigh_digits(self) -> None:
        self.ws_sum = 0
        self.ws_weight = 10
        while not self.ws_weight < 2:
            self.ws_i = 11 - self.ws_weight
            self.ws_digit = ord(self.ws_account[self.ws_i - 1]) - ord("0")
            self.ws_sum = (self.ws_sum + self.ws_digit * self.ws_weight) % 1000
            self.ws_weight -= 1

    def derive_check(self) -> None:
        self.ws_quot = (self.ws_sum // 11) % 1000
        self.ws_rem = (self.ws_sum % 11) % 100
        if self.ws_rem == 0:
            self.ws_check = 0
        elif self.ws_rem == 1:
            self.ws_check = 10
        else:
            self.ws_check = (11 - self.ws_rem) % 100

    def report_result(self) -> None:
        self.ws_given = ord(self.ws_account[9]) - ord("0")
        if self.ws_check == 10:
            self.ws_check_x = "X"
            self.ws_result = "NOCHECK"
        else:
            self.ws_check_d = self.ws_check % 10
            self.ws_check_x = num(self.ws_check_d, 1)
            if self.ws_check_d == self.ws_given:
                self.ws_result = pad("VALID", 7)
                self.ws_valid_count = (self.ws_valid_count + 1) % 10
            else:
                self.ws_result = pad("INVALID", 7)
        self._out.append(num(self.ws_acct_no, 1) + " " + self.ws_account + " " + self.ws_result
                         + " CHECK=" + self.ws_check_x + " SUM=" + num(self.ws_sum, 3)
                         + " Q=" + num(self.ws_quot, 3) + " R=" + num(self.ws_rem, 2) + "\n")

    def accept_alnum(self, n: int) -> str:
        """ACCEPT into X(n): first n characters, space padded; at end of input: spaces."""
        if not self._lines:
            return " " * n
        return pad(self._lines.pop(0), n)


def main() -> None:
    prog = Checkdig(sys.stdin.buffer.read())
    prog.main_para()
    sys.stdout.buffer.write("".join(prog._out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(prog.return_code)


if __name__ == "__main__":
    main()
