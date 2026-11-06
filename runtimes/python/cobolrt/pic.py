"""COBOL data descriptions: numeric and alphanumeric PICTUREs, usages and option constants.

The numbers used here are shared by the Java (`cobolrt.Usage`, `cobolrt.Round`, ...) and Go
runtimes, so a field description can be passed between languages as plain integers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class Usage(IntEnum):
    """Storage format of a numeric item."""

    DISPLAY = 0  # zoned decimal, one ASCII digit per byte (sign overpunch or separate)
    COMP = 1  # COMP / COMP-4 / BINARY: big-endian two's complement, truncated to PIC digits
    COMP3 = 2  # COMP-3 / PACKED-DECIMAL: BCD nibbles + sign nibble C/D/F
    COMP5 = 3  # COMP-5: native (little-endian) binary, limited by the byte width, not the PIC


class Round(IntEnum):
    """The ROUNDED phrase of a statement.

    TRUNCATION means *no* ROUNDED phrase. ROUNDED is a plain `ROUNDED` (default mode, which is
    nearest-away-from-zero everywhere except ADD/SUBTRACT into a COMP-3 item, where GnuCOBOL 3.2
    truncates - measured); the others are `ROUNDED MODE IS <mode>`, MODE_TRUNCATION being
    `ROUNDED MODE IS TRUNCATION`.
    """

    TRUNCATION = 0
    ROUNDED = 1
    NEAREST_AWAY_FROM_ZERO = 2
    AWAY_FROM_ZERO = 3
    NEAREST_EVEN = 4
    NEAREST_TOWARD_ZERO = 5
    TOWARD_GREATER = 6
    TOWARD_LESSER = 7
    PROHIBITED = 8
    MODE_TRUNCATION = 9


ROUNDED = Round.ROUNDED


class SizeError(IntEnum):
    """Which SIZE ERROR phrases the statement has."""

    NONE = 0  # neither phrase: overflow truncates (COMP-5 wraps) silently
    ON = 1  # ON SIZE ERROR present (with or without NOT ON SIZE ERROR)
    NOT_ONLY = 2  # only NOT ON SIZE ERROR present


# GnuCOBOL `binary-size: 1-2-4-8`
def binary_bytes(digits: int) -> int:
    if digits <= 2:
        return 1
    if digits <= 4:
        return 2
    if digits <= 9:
        return 4
    return 8


# DISPLAY width of COMP-5 items by byte width (libcob termio.c `bin_digits`, measured)
COMP5_DISPLAY_DIGITS = {1: 3, 2: 5, 4: 10, 8: 20}


@dataclass(frozen=True)
class NumPic:
    """A numeric elementary item.

    `digits` counts the digit positions that are stored (the 9s; P positions are not stored),
    `scale` is the power of ten the stored integer is divided by: `9(3)V99` -> (5, 2),
    `9(3)PP` -> (3, -2), `PP99` / `VPP99` -> (2, 4).
    """

    digits: int
    scale: int = 0
    signed: bool = False
    usage: Usage = Usage.DISPLAY
    sign_leading: bool = False  # SIGN IS LEADING (DISPLAY only; default is trailing)
    sign_separate: bool = False  # SIGN ... SEPARATE CHARACTER (DISPLAY only)

    def __post_init__(self) -> None:
        if not 1 <= self.digits <= 18:
            raise ValueError(f"digits must be 1..18, got {self.digits}")
        if (self.sign_leading or self.sign_separate) and (not self.signed or self.usage != Usage.DISPLAY):
            raise ValueError("SIGN LEADING/SEPARATE needs a signed DISPLAY item")

    @property
    def byte_length(self) -> int:
        if self.usage == Usage.DISPLAY:
            return self.digits + (1 if self.sign_separate else 0)
        if self.usage == Usage.COMP3:
            return self.digits // 2 + 1
        return binary_bytes(self.digits)

    @property
    def is_binary(self) -> bool:
        return self.usage in (Usage.COMP, Usage.COMP5)

    @property
    def max_unscaled(self) -> int:
        """Largest storable unscaled magnitude."""
        if self.usage == Usage.COMP5:
            bits = 8 * self.byte_length
            return (1 << (bits - 1)) - 1 if self.signed else (1 << bits) - 1
        return 10**self.digits - 1

    @property
    def min_unscaled(self) -> int:
        if not self.signed:
            return 0
        if self.usage == Usage.COMP5:
            return -(1 << (8 * self.byte_length - 1))
        return -(10**self.digits - 1)

    def picture(self) -> str:
        """A PICTURE string for this item (for messages and generated COBOL)."""
        s = "S" if self.signed else ""
        if self.scale <= 0:
            return f"{s}9({self.digits})" + ("P" * -self.scale)
        if self.scale >= self.digits:
            return f"{s}V" + "P" * (self.scale - self.digits) + f"9({self.digits})"
        return f"{s}9({self.digits - self.scale})V9({self.scale})"

    def usage_clause(self) -> str:
        u = {Usage.DISPLAY: "", Usage.COMP: "COMP", Usage.COMP3: "COMP-3", Usage.COMP5: "COMP-5"}[self.usage]
        if self.sign_separate or self.sign_leading:
            u = "SIGN " + ("LEADING" if self.sign_leading else "TRAILING") + (
                " SEPARATE" if self.sign_separate else "")
        return u


@dataclass(frozen=True)
class AlnumPic:
    """PIC X(n) [JUSTIFIED RIGHT]."""

    length: int
    justified: bool = False

    def __post_init__(self) -> None:
        if self.length < 1:
            raise ValueError("length must be >= 1")

    @property
    def byte_length(self) -> int:
        return self.length


_SYM = re.compile(r"([SVP9X])(?:\((\d+)\))?")


def parse_pic(picture: str, usage: str | Usage = Usage.DISPLAY, sign: str = "",
              justified: bool = False) -> NumPic | AlnumPic:
    """Parse a PICTURE string such as `S9(5)V99`, `9(3)PP`, `PP99`, `X(10)`.

    `usage` is `DISPLAY`, `COMP`, `COMP-4`, `BINARY`, `COMP-3`, `PACKED-DECIMAL` or `COMP-5`;
    `sign` is e.g. `LEADING SEPARATE` or `TRAILING`.
    """
    text = picture.upper().replace(" ", "")
    pos = 0
    syms: list[tuple[str, int]] = []
    while pos < len(text):
        m = _SYM.match(text, pos)
        if not m:
            raise ValueError(f"unsupported PICTURE {picture!r}")
        syms.append((m.group(1), int(m.group(2) or "1")))
        pos = m.end()
    if all(s == "X" for s, _ in syms):
        return AlnumPic(sum(n for _, n in syms), justified)
    signed = False
    digits = scale = 0
    seen_v = seen_9 = leading_p = False
    for s, n in syms:
        if s == "S":
            signed = True
        elif s == "V":
            seen_v = True
        elif s == "9":
            digits += n
            if seen_v or leading_p:
                scale += n
            seen_9 = True
        elif s == "P":
            if seen_v or not seen_9:
                scale += n
                leading_p = True
            else:
                scale -= n
        else:
            raise ValueError(f"unsupported PICTURE {picture!r}")
    u = _usage(usage)
    sg = sign.upper().split()
    return NumPic(digits, scale, signed, u, sign_leading="LEADING" in sg, sign_separate="SEPARATE" in sg)


def _usage(usage: str | Usage) -> Usage:
    if isinstance(usage, Usage):
        return usage
    u = usage.upper().replace("COMPUTATIONAL", "COMP").strip()
    table = {"": Usage.DISPLAY, "DISPLAY": Usage.DISPLAY, "COMP": Usage.COMP, "COMP-4": Usage.COMP,
             "BINARY": Usage.COMP, "COMP-3": Usage.COMP3, "PACKED-DECIMAL": Usage.COMP3,
             "COMP-5": Usage.COMP5}
    if u not in table:
        raise ValueError(f"unsupported USAGE {usage!r}")
    return table[u]
