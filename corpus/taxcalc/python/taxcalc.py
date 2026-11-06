"""Hand translation of TAXCALC. Numerics are ints scaled by 10**scale (WS-INCOME PIC 9(6)V99 holds
cents); module-level state and functions, one function per paragraph."""

from __future__ import annotations

import sys

ws_category: int = 0  # 9
ws_income_k: int = 0  # 9(2)
ws_income: int = 0  # 9(6)V99, scale 2
ws_deduction: int = 0  # 9(5)V99, scale 2
ws_taxable: int = 0  # S9(6)V99, scale 2
ws_gap: int = 0  # 9(6)V99, scale 2
ws_rate: int = 0  # V999, scale 3
ws_bracket: str = " " * 6  # X(6)
ws_tax: int = 0  # 9(5)V99
ws_tax_trunc: int = 0  # 9(5)V99
ws_surcharge: int = 0  # 9(3)V99 VALUE 0
ws_total_tax: int = 0  # 9(5)V99
ws_eff_rate: int = 0  # 9(2)V99 VALUE 0
ws_size_flag: str = "N"  # X VALUE "N"
ws_rate_flag: str = "N"  # X VALUE "N"
return_code: int = 0

_lines: list[str] = []
_out: list[str] = []


def main_para() -> None:
    global return_code
    read_input()
    if ws_category <= 3:  # CAT-VALID: 0 THRU 3
        compute_tax()
        show_result()
    else:
        line("INVALID CATEGORY " + unsigned(ws_category, 1, 0))
        return_code = 4


def read_input() -> None:
    global ws_category, ws_income_k
    ws_category = accept_numeric(1, 1, 0)
    ws_income_k = accept_numeric(2, 2, 0)


def compute_tax() -> None:
    global ws_income, ws_deduction, ws_taxable, ws_gap, ws_rate, ws_bracket, ws_tax, ws_tax_trunc
    global ws_surcharge, ws_size_flag, ws_total_tax, ws_rate_flag, ws_eff_rate, return_code
    ws_income = (ws_income_k * 1000 * 100) % 100000000
    if ws_category == 0:
        ws_deduction = 9999999
    elif ws_category == 1:
        ws_deduction = 1255000
    elif ws_category == 2:
        ws_deduction = 2510000
    else:
        ws_deduction = 1880050
    diff = ws_income - ws_deduction
    ws_taxable = -(abs(diff) % 100000000) if diff < 0 else diff % 100000000
    ws_gap = abs(diff) % 100000000  # unsigned target: the sign is dropped
    if ws_taxable < 0:
        ws_taxable = 0
    if ws_income_k <= 9:
        ws_rate = 0
        ws_bracket = "NIL   "
    elif ws_income_k <= 39:
        ws_rate = 100
        ws_bracket = "LOW   "
    elif ws_income_k <= 84:
        ws_rate = 225
        ws_bracket = "MIDDLE"
    else:
        ws_rate = 333
        ws_bracket = "HIGH  "
    product = ws_taxable * ws_rate  # scale 5, never negative
    ws_tax = ((product + 500) // 1000) % 10000000  # ROUNDED to scale 2
    ws_tax_trunc = (product // 1000) % 10000000  # truncated
    surcharge = (ws_tax * 75 + 500) // 1000  # WS-TAX * 0.075, ROUNDED
    overflow = surcharge > 99999  # 9(3)V99: ON SIZE ERROR
    if overflow:
        ws_size_flag = "Y"  # target left unchanged
    else:
        ws_surcharge = surcharge
        ws_size_flag = "N"
    ws_total_tax = (ws_tax + ws_surcharge) % 10000000
    if ws_income == 0:
        ws_rate_flag = "Z"  # divide by zero: size error
    else:
        n = ws_total_tax * 10000  # (total * 100 / income) at scale 2
        q, r = divmod(n, ws_income)
        if 2 * r >= ws_income:
            q += 1
        if q > 9999:
            ws_rate_flag = "Z"
        else:
            ws_eff_rate = q
    if overflow:
        return_code = 2


def show_result() -> None:
    line("CATEGORY " + unsigned(ws_category, 1, 0) + " INCOME " + unsigned(ws_income, 6, 2)
         + " BRACKET " + ws_bracket)
    line("DEDUCTION " + unsigned(ws_deduction, 5, 2) + " TAXABLE " + signed(ws_taxable, 6, 2)
         + " GAP " + unsigned(ws_gap, 6, 2))
    line("TAX " + unsigned(ws_tax, 5, 2) + " TRUNC " + unsigned(ws_tax_trunc, 5, 2)
         + " SURCHARGE " + unsigned(ws_surcharge, 3, 2) + " OVERFLOW " + ws_size_flag)
    line("TOTAL " + unsigned(ws_total_tax, 5, 2) + " EFFECTIVE " + unsigned(ws_eff_rate, 2, 2)
         + "% FLAG " + ws_rate_flag)


# ---------------------------------------------------------------------- runtime helpers
def line(s: str) -> None:
    _out.append(s + "\n")


def unsigned(v: int, int_digits: int, scale: int) -> str:
    s = str(abs(v)).rjust(int_digits + scale, "0")
    return s[: len(s) - scale] + "." + s[len(s) - scale:] if scale > 0 else s


def signed(v: int, int_digits: int, scale: int) -> str:
    return ("-" if v < 0 else "+") + unsigned(v, int_digits, scale)


def accept_numeric(window: int, int_digits: int, scale: int) -> int:
    """ACCEPT into an unsigned numeric DISPLAY field: first `window` characters, de-edited; EOF gives 0."""
    if not _lines:
        return 0
    w = _lines.pop(0)[:window]
    i, n = 0, len(w)
    while i < n and w[i] == " ":
        i += 1
    if i < n and w[i] in "+-":
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
    v = 0
    for c in ip[-int_digits:]:
        v = v * 10 + ord(c) - 48
    for k in range(scale):
        v = v * 10 + (ord(fp[k]) - 48 if k < len(fp) else 0)
    return v  # unsigned field: the sign is dropped


def main() -> None:
    data = sys.stdin.buffer.read().decode("latin-1")
    parts = data.split("\n") if data else []
    if data.endswith("\n"):
        parts.pop()
    _lines.extend(parts)
    main_para()
    sys.stdout.buffer.write("".join(_out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(return_code)


if __name__ == "__main__":
    main()
