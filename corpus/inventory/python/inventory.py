"""Hand translation of INVENTORY. Numerics are ints scaled by 10**scale. Record fields are decoded
from / encoded to the exact GnuCOBOL byte layouts: COMP-3 (packed, sign nibble C/D/F), COMP
(big-endian two's complement), zoned with ASCII overpunch (negative last digit = 0x70 + d) and
SIGN LEADING / TRAILING SEPARATE."""

from __future__ import annotations

import sys

STK_LEN = 21
VAL_LEN = 32


# ------------------------------------------------------------------------- record codecs
def packed_is_numeric(b: bytes, off: int, n: int, is_signed: bool) -> bool:
    for i in range(n):
        hi, lo = b[off + i] >> 4, b[off + i] & 0xF
        if hi > 9 or (i < n - 1 and lo > 9):
            return False
    sign = b[off + n - 1] & 0xF
    return sign in (0xC, 0xD) if is_signed else sign == 0xF


def unpack(b: bytes, off: int, n: int) -> int:
    v = 0
    for i in range(n):
        v = v * 10 + (b[off + i] >> 4)
        if i < n - 1:
            v = v * 10 + (b[off + i] & 0xF)
    return -v if (b[off + n - 1] & 0xF) == 0xD else v


def pack(v: int, n: int, is_signed: bool) -> bytes:
    a = abs(v)
    nibbles = [0] * (2 * n)
    nibbles[-1] = (0xD if v < 0 else 0xC) if is_signed else 0xF
    for i in range(2 * n - 2, -1, -1):
        nibbles[i] = a % 10
        a //= 10
    return bytes((nibbles[2 * i] << 4) | nibbles[2 * i + 1] for i in range(n))


def zoned_is_numeric(b: bytes, off: int, n: int) -> bool:
    if any(not 0x30 <= b[off + i] <= 0x39 for i in range(n - 1)):
        return False
    last = b[off + n - 1]
    return 0x30 <= last <= 0x39 or 0x70 <= last <= 0x79


def unzone(b: bytes, off: int, n: int) -> int:
    v = 0
    for i in range(n - 1):
        v = v * 10 + b[off + i] - 0x30
    last = b[off + n - 1]
    if last >= 0x70:
        return -(v * 10 + last - 0x70)
    return v * 10 + last - 0x30


def leading_separate_is_numeric(b: bytes, off: int, n: int) -> bool:
    return b[off] in b"+-" and all(0x30 <= b[off + i] <= 0x39 for i in range(1, n))


def comp_s16(b: bytes, off: int) -> int:
    v = (b[off] << 8) | b[off + 1]
    return v - 0x10000 if v >= 0x8000 else v


def digits(v: int, n: int) -> str:
    return str(abs(v)).rjust(n, "0")


def with_point(ds: str, scale: int) -> str:
    return ds if scale == 0 else ds[: len(ds) - scale] + "." + ds[len(ds) - scale:]


def signed(v: int, int_digits: int, scale: int) -> str:
    return ("-" if v < 0 else "+") + with_point(digits(v, int_digits + scale), scale)


class Inventory:
    def __init__(self) -> None:
        # FD STOCK-FILE
        self.stk_item: str = " " * 6  # X(6)
        self.stk_qty: int = 0  # S9(5) COMP-3
        self.stk_cost: int = 0  # 9(4)V99 COMP-3, scale 2
        self.stk_reorder: int = 0  # S9(4) COMP
        self.stk_adj: int = 0  # S9(3)
        self.stk_disc: int = 0  # SV99 SIGN LEADING SEPARATE, scale 2
        self._stk_rec = bytes(STK_LEN)
        # FD VALUE-FILE
        self.val_item: str = " " * 6  # X(6)
        self.val_new_qty: int = 0  # S9(5) COMP-3
        self.val_unit: int = 0  # S9(4)V99 COMP-3
        self.val_amount: int = 0  # S9(8)V99 COMP-3
        self.val_count: int = 0  # 9(4) COMP
        self.val_flag: str = " "  # X
        self.val_net: int = 0  # S9(7)V99 SIGN TRAILING SEPARATE (digits)
        self._val_unit_sign_f = False
        self._val_net_negative = False
        # WORKING-STORAGE
        self.ws_eof: str = "N"
        self.ws_valid: str = " "
        self.ws_item: str = " " * 6
        self.ws_qty: int = 0  # S9(5) COMP-3
        self.ws_cost: int = 0  # 9(4)V99 COMP-3
        self.ws_reorder: int = 0  # S9(4) COMP
        self.ws_adj: int = 0  # S9(3)
        self.ws_disc: int = 0  # SV99 SIGN LEADING SEPARATE
        self.ws_unit: int = 0  # S9(4)V99 COMP-3
        # a packed MOVE from the unsigned WS-COST keeps sign nibble F in the signed WS-UNIT;
        # arithmetic results always get C/D (visible in VALUE.DAT)
        self._ws_unit_sign_f = False
        self.ws_amount: int = 0  # S9(8)V99 COMP-3
        self.ws_status: str = " "  # X
        self.ws_rec_count: int = 0  # 9(4) COMP
        self.ws_reject_count: int = 0
        self.ws_neg_count: int = 0
        self.ws_reorder_count: int = 0
        self.ws_total_value: int = 0  # S9(11)V99 COMP-3
        self.return_code: int = 0
        self._stock = b""
        self._stock_pos = 0
        self._value_file = bytearray()
        self._out: list[str] = []

    def main_para(self) -> None:
        with open("STOCK.DAT", "rb") as f:
            self._stock = f.read()
        self._stock_pos = 0
        self.read_stock()
        while self.ws_eof != "Y":
            self.validate_record()
            if self.ws_valid == "Y":
                self.value_item()
            else:
                self.reject_item()
            self.write_value()
            self.read_stock()
        with open("VALUE.DAT", "wb") as f:
            f.write(bytes(self._value_file))
        self.set_return()
        self.show_totals()

    def read_stock(self) -> None:
        if self._stock_pos + STK_LEN > len(self._stock):
            self.ws_eof = "Y"
            return
        self._stk_rec = self._stock[self._stock_pos:self._stock_pos + STK_LEN]
        self._stock_pos += STK_LEN
        self.stk_item = self._stk_rec[0:6].decode("latin-1")

    def validate_record(self) -> None:
        rec = self._stk_rec
        self.ws_valid = "N"
        self.ws_item = self.stk_item
        if (packed_is_numeric(rec, 6, 3, True) and packed_is_numeric(rec, 9, 4, False)
                and zoned_is_numeric(rec, 15, 3) and leading_separate_is_numeric(rec, 18, 3)):
            self.ws_valid = "Y"
            self.stk_qty = unpack(rec, 6, 3)
            self.stk_cost = unpack(rec, 9, 4)
            self.stk_reorder = comp_s16(rec, 13)
            self.stk_adj = unzone(rec, 15, 3)
            self.stk_disc = (-1 if rec[18] == 0x2D else 1) * int(rec[19:21].decode("latin-1"))
            self.ws_qty = self.stk_qty
            self.ws_cost = self.stk_cost
            self.ws_reorder = self.stk_reorder
            self.ws_adj = self.stk_adj
            self.ws_disc = self.stk_disc

    def value_item(self) -> None:
        self.ws_status = " "
        q = self.ws_qty + self.ws_adj
        if q > 99999 or q < -99999:
            self.ws_status = "O"  # ON SIZE ERROR: WS-QTY unchanged
        else:
            self.ws_qty = q
        product = self.ws_cost * (100 + self.ws_disc)  # scale 4, never negative
        unit = (product + 50) // 100  # ROUNDED to scale 2
        if unit > 999999:
            self.ws_unit = self.ws_cost
            self._ws_unit_sign_f = True
            self.ws_status = "P"
        else:
            self.ws_unit = unit
            self._ws_unit_sign_f = False
        amount = self.ws_qty * self.ws_unit  # scale 2
        if amount > 9999999999 or amount < -9999999999:
            self.ws_amount = 0
            self.ws_status = "V"
        else:
            self.ws_amount = amount
        if self.ws_status != " ":
            pass  # already flagged (WHEN NOT STATUS-OK: CONTINUE)
        elif self.ws_qty < 0:
            self.ws_status = "N"
            self.ws_neg_count = (self.ws_neg_count + 1) % 10000
        elif self.ws_qty < self.ws_reorder:
            self.ws_status = "R"
            self.ws_reorder_count = (self.ws_reorder_count + 1) % 10000
        self.ws_total_value = self.ws_total_value + self.ws_amount

    def reject_item(self) -> None:
        self.ws_status = "X"
        self.ws_qty = 0
        self.ws_unit = 0
        self._ws_unit_sign_f = False
        self.ws_amount = 0
        self.ws_reject_count = (self.ws_reject_count + 1) % 10000

    def write_value(self) -> None:
        self.ws_rec_count = (self.ws_rec_count + 1) % 10000
        self.val_item = self.ws_item
        self.val_new_qty = self.ws_qty
        self.val_unit = self.ws_unit
        self._val_unit_sign_f = self._ws_unit_sign_f
        self.val_amount = self.ws_amount
        self.val_count = self.ws_rec_count
        self.val_flag = self.ws_status
        self.val_net = abs(self.ws_amount) % 1000000000  # MOVE: high-order truncation
        self._val_net_negative = self.ws_amount < 0  # MOVE keeps the source sign
        rec = bytearray(VAL_LEN)
        rec[0:6] = self.val_item.encode("latin-1")
        rec[6:9] = pack(self.val_new_qty, 3, True)
        rec[9:13] = pack(self.val_unit, 4, not self._val_unit_sign_f)
        rec[13:19] = pack(self.val_amount, 6, True)
        rec[19] = (self.val_count >> 8) & 0xFF
        rec[20] = self.val_count & 0xFF
        rec[21] = ord(self.val_flag[0])
        rec[22:32] = (digits(self.val_net, 9) + ("-" if self._val_net_negative else "+")).encode("latin-1")
        self._value_file.extend(rec)
        net_shown = with_point(digits(self.val_net, 9), 2) + ("-" if self._val_net_negative and self.val_net != 0
                                                                else "+")
        self.line(digits(self.ws_rec_count, 4) + " " + self.ws_item + " QTY " + signed(self.ws_qty, 5, 0)
                  + " UNIT " + signed(self.ws_unit, 4, 2) + " AMOUNT " + signed(self.ws_amount, 8, 2)
                  + " [" + self.ws_status + "] NET " + net_shown)

    def set_return(self) -> None:
        if self.ws_reject_count > 0:
            self.return_code = 12
        elif self.ws_neg_count > 0:
            self.return_code = 8
        elif self.ws_reorder_count > 0:
            self.return_code = 4
        else:
            self.return_code = 0

    def show_totals(self) -> None:
        self.line("RECORDS " + digits(self.ws_rec_count, 4) + " REJECTED " + digits(self.ws_reject_count, 4)
                  + " NEGATIVE " + digits(self.ws_neg_count, 4) + " REORDER " + digits(self.ws_reorder_count, 4))
        self.line("TOTAL VALUE " + signed(self.ws_total_value, 11, 2))

    def line(self, s: str) -> None:
        self._out.append(s + "\n")


def main() -> None:
    prog = Inventory()
    prog.main_para()
    sys.stdout.buffer.write("".join(prog._out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(prog.return_code)


if __name__ == "__main__":
    main()
