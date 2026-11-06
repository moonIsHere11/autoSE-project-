"""Hand translation of T2APROG with module-level state (decimals as ints scaled by 10**scale)."""

from __future__ import annotations

import sys

ws_qty: int = 0  # 9(2)
ws_code: int = 0  # 9
ws_price: int = 0  # 9(3)V99, scale 2
ws_total: int = 0  # 9(4)V99, scale 2
ws_disc: int = 0  # 9(3)V99, scale 2
ws_net: int = 0  # S9(4)V99, scale 2

_lines: list[str] = []
_out: list[str] = []


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


def accept(current: int, window: int, int_digits: int) -> int:
    if not _lines:
        return current
    return deedit(_lines.pop(0)[:window], int_digits, 0, False)


def fmt(v: int, int_digits: int, scale: int) -> str:
    s = str(abs(v)).rjust(int_digits + scale, "0")
    return s[: len(s) - scale] + "." + s[len(s) - scale:]


def main_para() -> None:
    global ws_qty, ws_code
    ws_qty = accept(ws_qty, 2, 2)
    ws_code = accept(ws_code, 1, 1)
    calc_para()
    _out.append("TOTAL=" + fmt(ws_total, 4, 2) + " NET=" + ("-" if ws_net < 0 else "+") + fmt(ws_net, 4, 2) + "\n")


def calc_para() -> None:
    global ws_price, ws_total, ws_disc, ws_net
    if ws_code == 0:
        ws_price = 125
    elif 1 <= ws_code <= 4:
        ws_price = 1999
    else:
        ws_price = 750
    # qty * price (scale 2) * 1.075 (scale 3) is exact at scale 5; ROUNDED to scale 2 (all >= 0)
    exact = ws_qty * ws_price * 1075
    ws_total = ((exact + 500) // 1000) % 1000000
    if ws_qty > 50:  # noqa: SIM108 (one branch per COBOL branch)
        ws_disc = ((ws_total * 125 + 500) // 1000) % 100000
    else:
        ws_disc = 0
    ws_net = (ws_total - ws_disc) % 1000000


def main() -> None:
    data = sys.stdin.buffer.read().decode("latin-1")
    parts = data.split("\n") if data else []
    if data.endswith("\n"):
        parts.pop()
    _lines.extend(parts)
    main_para()
    sys.stdout.buffer.write("".join(_out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(0)


if __name__ == "__main__":
    main()
