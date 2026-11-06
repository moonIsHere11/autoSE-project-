"""Alphanumeric semantics on fixed-length byte strings (ISO-8859-1), plus numeric<->alphanumeric
MOVEs and ACCEPT parsing (libcob move.c / termio.c)."""

from __future__ import annotations

from cobolrt.num import move_value
from cobolrt.pic import AlnumPic, NumPic, Usage

SPACE = 0x20
_ISSPACE = b" \t\n\v\f\r"


def to_bytes(s: str | bytes | bytearray) -> bytes:
    return s.encode("latin-1") if isinstance(s, str) else bytes(s)


def move(src: str | bytes, length: int, justified: bool = False) -> bytes:
    """MOVE alphanumeric -> PIC X(length): left-aligned, space padded, truncated on the right;
    JUSTIFIED RIGHT aligns right and truncates on the left."""
    b = to_bytes(src)
    if len(b) >= length:
        return b[len(b) - length:] if justified else b[:length]
    pad = b" " * (length - len(b))
    return pad + b if justified else b + pad


def compare(a: str | bytes, b: str | bytes) -> int:
    """Alphanumeric comparison: the shorter operand is padded with spaces; native byte order."""
    x, y = to_bytes(a), to_bytes(b)
    n = max(len(x), len(y))
    x, y = x.ljust(n, b" "), y.ljust(n, b" ")
    return (x > y) - (x < y)


def refmod(data: str | bytes, start: int, length: int | None = None) -> bytes:
    """Reference modification `item(start:length)` with a 1-based start."""
    b = to_bytes(data)
    if start < 1 or start > len(b):
        raise IndexError(f"reference modification start {start} outside 1..{len(b)}")
    n = len(b) - start + 1 if length is None else length
    if n < 1 or start - 1 + n > len(b):
        raise IndexError(f"reference modification length {n} out of range")
    return b[start - 1:start - 1 + n]


def set_refmod(data: bytes, start: int, length: int | None, value: str | bytes) -> bytes:
    """MOVE value TO item(start:length): the slice is treated as PIC X(length)."""
    b = to_bytes(data)
    n = len(b) - start + 1 if length is None else length
    refmod(b, start, n)
    return b[:start - 1] + move(value, n) + b[start - 1 + n:]


# ---------------------------------------------------------------------------------------------
# numeric -> alphanumeric
# ---------------------------------------------------------------------------------------------
def num_to_alnum(u: int, pic: NumPic, length: int, justified: bool = False) -> bytes:
    """MOVE integer numeric item -> PIC X: the digits without sign (cob_move_display_to_alphanum);
    trailing P positions become zeros. COBOL only allows this for integer items (scale <= 0)."""
    if pic.scale > 0:
        raise ValueError("MOVE of a non-integer numeric item to alphanumeric is not allowed")
    if pic.usage == Usage.DISPLAY and not pic.signed and pic.digits >= length:
        # cobc copies the leading bytes (cb_build_move_copy), JUSTIFIED is ignored
        return str(abs(u) % 10**pic.digits).rjust(pic.digits, "0").encode("ascii")[:length]
    # non-DISPLAY items go through a temporary DISPLAY item of GnuCOBOL's digit count (which
    # includes P positions); either way the P positions are appended as zeros
    n = pic.digits if pic.usage == Usage.DISPLAY else pic.digits - pic.scale
    digits = str(abs(u) % 10**n).rjust(n, "0").encode("ascii")
    zeros = -pic.scale
    size1 = len(digits)
    if justified:
        out = bytearray(b" " * length)
        size2 = length
        if zeros:
            z = min(zeros, size2)
            size2 -= z
            out[size2:size2 + z] = b"0" * z
        if size2:
            diff = size2 - size1
            if diff > 0:
                out[diff:size2] = digits
            else:
                out[0:size2] = digits[size1 - size2:]
        return bytes(out)
    if length < size1:
        return digits[:length]
    out = bytearray(digits)
    rest = length - size1
    z = min(zeros, rest)
    out += b"0" * z + b" " * (rest - z)
    return bytes(out)


# ---------------------------------------------------------------------------------------------
# alphanumeric -> numeric (de-editing), ACCEPT
# ---------------------------------------------------------------------------------------------
def deedit(src: bytes, size: int, scale: int) -> tuple[int, int]:
    """cob_move_alphanum_to_display: text -> (magnitude, sign) for a DISPLAY item with `size`
    stored digits and `scale`. Leading white space, one `+`/`-`, digits, at most one `.`, spaces
    and `,` are accepted; anything else gives zero. Digits beyond the item are dropped."""
    data = bytearray(b"0" * size)
    e1 = len(src)
    s1 = 0
    while s1 < e1 and src[s1] in _ISSPACE:
        s1 += 1
    sg = 0
    if s1 != e1 and src[s1] in b"+-":
        sg = 1 if src[s1] == 0x2B else -1
        s1 += 1
    count = 0
    p = s1
    while p < e1 and src[p] != 0x2E:
        if 0x30 <= src[p] <= 0x39:
            count += 1
        p += 1
    isize = size - scale
    s2 = 0
    if count < isize:
        s2 = isize - count
    else:
        while count > isize:
            # (GnuCOBOL reads past the input here when a leading-P item gets too few digits;
            # that is undefined there, the runtime simply stops at the end of the text)
            while s1 < e1 and not 0x30 <= src[s1] <= 0x39:
                s1 += 1
            s1 += 1
            count -= 1
    points = 0
    while s1 < e1 and s2 < size:
        c = src[s1]
        if 0x30 <= c <= 0x39:
            data[s2] = c
            s2 += 1
        elif c == 0x2E:
            points += 1
            if points > 1:
                return 0, 0
        elif not (c in _ISSPACE or c == 0x2C):
            return 0, 0
        s1 += 1
    return int(data), sg


_TEMP_SIZE, _TEMP_SCALE = 76, 38  # indirect_move temporary (2*COB_MAX_DIGITS, COB_MAX_DIGITS)


def alnum_to_num(src: str | bytes, pic: NumPic) -> tuple[int, bool]:
    """MOVE alphanumeric -> numeric item. Returns (unscaled, negzero)."""
    b = to_bytes(src)
    if pic.usage == Usage.DISPLAY:
        mag, sg = deedit(b, pic.digits, pic.scale)
        if not pic.signed:
            return mag, False
        return (-mag if sg < 0 else mag), sg < 0 and mag == 0
    mag, sg = deedit(b, _TEMP_SIZE, _TEMP_SCALE)
    return move_value(-mag if sg < 0 else mag, _TEMP_SCALE, sg < 0, False, pic)


def accept_num(line: str | bytes | None, pic: NumPic) -> tuple[int, bool]:
    """ACCEPT numeric-item FROM stdin: `line` without its newline, None at end of input.

    DISPLAY items take only the first byte-length characters of the line; COMP/COMP-3/COMP-5
    take the whole line. At end of input the item is set to zero.
    """
    b = b" " if line is None else to_bytes(line)
    if not b:
        b = b""
    if pic.usage == Usage.DISPLAY:
        b = b[:pic.byte_length]
    return alnum_to_num(b, pic)


def accept_alnum(line: str | bytes | None, pic: AlnumPic) -> bytes:
    """ACCEPT PIC X item: first n characters, space padded (right-aligned if JUSTIFIED)."""
    b = b" " if line is None else to_bytes(line)
    return move(b, pic.length, pic.justified)
