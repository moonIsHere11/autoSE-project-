"""Field values <-> bytes, exactly as GnuCOBOL 3.2 stores and displays them (spike S6).

Values are passed around as canonical decimal text (`"-123.45"`, `"0"`, `"-0"` for an explicit
negative zero) for numerics and as plain strings for alphanumerics.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from verifier.cobol.datadiv import DataItem, PicInfo, binary_bytes


class EncodeError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------------------------
def to_decimal(text: str) -> Decimal:
    try:
        return Decimal(text.strip())
    except InvalidOperation as exc:
        raise EncodeError(f"not a number: {text!r}") from exc


def is_negative_zero(text: str) -> bool:
    t = text.strip()
    return t.startswith("-") and to_decimal(t) == 0


def scaled_int(value: Decimal, pic: PicInfo) -> int:
    """Integer of the stored digits (value * 10^scale), truncated like a COBOL MOVE."""
    q = (value * (Decimal(10) ** pic.scale)).to_integral_value(rounding="ROUND_DOWN")
    n: int = int(q)
    mod = 10**pic.digits
    n = (abs(n) % mod) * (1 if n >= 0 else -1)
    if not pic.signed:
        n = abs(n)
    return n


def from_scaled(n: int, pic: PicInfo) -> Decimal:
    return Decimal(n).scaleb(-pic.scale)


def canonical_text(value: Decimal, scale: int) -> str:
    """`[-]digits[.digits]` with exactly `scale` decimals (scale <= 0 => integer)."""
    q = value.quantize(Decimal(1).scaleb(-max(scale, 0)))
    s = format(q, "f")
    return "0" + s[s.index("-") + 1 :] if s.startswith("-0") and q == 0 else s


def field_max(pic: PicInfo) -> Decimal:
    return from_scaled(10**pic.digits - 1, pic)


def ulp(pic: PicInfo) -> Decimal:
    return Decimal(1).scaleb(-pic.scale)


# ---------------------------------------------------------------------------------------------
# storage encodings
# ---------------------------------------------------------------------------------------------
def zoned(item: DataItem, text: str) -> bytes:
    pic = item.pic
    assert pic is not None
    v = to_decimal(text)
    n = scaled_int(v, pic)
    neg = n < 0 or (pic.signed and is_negative_zero(text))
    digits = str(abs(n)).rjust(pic.digits, "0")
    if not pic.signed:
        return digits.encode("ascii")
    sign = item.sign or "TRAILING"
    if item.sign_separate:
        ch = "-" if neg else "+"
        return (ch + digits if sign == "LEADING" else digits + ch).encode("ascii")
    if not neg:
        return digits.encode("ascii")
    if sign == "LEADING":
        return bytes([0x70 + int(digits[0])]) + digits[1:].encode("ascii")
    return digits[:-1].encode("ascii") + bytes([0x70 + int(digits[-1])])


def packed(item: DataItem, text: str) -> bytes:
    pic = item.pic
    assert pic is not None
    n = scaled_int(to_decimal(text), pic)
    size = pic.digits // 2 + 1
    digits = str(abs(n)).rjust(size * 2 - 1, "0")
    sign = 0xF if not pic.signed else (0xD if n < 0 else 0xC)
    nibbles = [int(c) for c in digits] + [sign]
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def binary(item: DataItem, text: str) -> bytes:
    pic = item.pic
    assert pic is not None
    size = binary_bytes(pic.digits)
    v = to_decimal(text)
    if item.usage == "COMP-5":
        n = int((v * (Decimal(10) ** pic.scale)).to_integral_value(rounding="ROUND_DOWN"))
        n %= 1 << (8 * size)
        return n.to_bytes(size, "little")
    n = scaled_int(v, pic)
    if pic.signed:
        return n.to_bytes(size, "big", signed=True)
    return abs(n).to_bytes(size, "big")


def alnum(item: DataItem, value: str) -> bytes:
    length = item.unit_size
    raw = value.encode("latin-1", errors="replace")
    if len(raw) >= length:
        return raw[-length:] if item.justified else raw[:length]
    return raw.rjust(length) if item.justified else raw.ljust(length)


def encode_elementary(item: DataItem, value: str) -> bytes:
    if item.pic is None:
        raise EncodeError(f"{item.name}: no PICTURE")
    if item.pic.category != "numeric":
        return alnum(item, value)
    if item.usage == "DISPLAY":
        return zoned(item, value)
    if item.usage == "COMP-3":
        return packed(item, value)
    if item.usage in ("COMP", "COMP-5"):
        return binary(item, value)
    raise EncodeError(f"{item.name}: USAGE {item.usage} not supported for input generation")


def default_value(item: DataItem) -> str:
    if item.pic is not None and item.pic.category == "numeric":
        return "0"
    return ""


def encode_record(record: DataItem, values: dict[str, str]) -> bytes:
    """Encode a record (group or elementary) from field values; missing fields get defaults."""
    buf = bytearray(b" " * record.size)

    def put(item: DataItem, base: int) -> None:
        if item.redefines:
            return
        if item.children:
            for occ in range(item.occurs or 1):
                for c in item.children:
                    put(c, base + occ * item.unit_size)
            return
        if item.level in (66, 88):
            return
        val = values.get(item.name, default_value(item)) if not item.is_filler else ""
        data = encode_elementary(item, val) if not item.is_filler else b" " * item.unit_size
        for occ in range(item.occurs or 1):
            off = base + (item.offset - record.offset) + occ * item.unit_size
            buf[off : off + item.unit_size] = data

    if record.children:
        for occ in range(record.occurs or 1):
            for c in record.children:
                put(c, occ * record.unit_size)
    else:
        put(record, 0)
    return bytes(buf)


# ---------------------------------------------------------------------------------------------
# decoding (for diagnosis)
# ---------------------------------------------------------------------------------------------
def decode_elementary(item: DataItem, data: bytes) -> str:
    """Best-effort decode of stored bytes to a value text; raw escape on failure."""
    pic = item.pic
    if pic is None or pic.category != "numeric":
        return data.decode("latin-1")
    try:
        if item.usage == "DISPLAY":
            s = data.decode("latin-1")
            neg = False
            if item.sign_separate:
                if (item.sign or "TRAILING") == "LEADING":
                    neg, s = s[0] == "-", s[1:]
                else:
                    neg, s = s[-1] == "-", s[:-1]
            elif pic.signed:
                idx = 0 if item.sign == "LEADING" else len(s) - 1
                c = ord(s[idx])
                if 0x70 <= c <= 0x79:
                    neg = True
                    s = s[:idx] + chr(c - 0x40) + s[idx + 1 :]
            if not s.isdigit():
                return _raw(data)
            n = int(s)
        elif item.usage == "COMP-3":
            nib = []
            for b in data:
                nib += [b >> 4, b & 0xF]
            sign = nib[-1]
            if any(d > 9 for d in nib[:-1]):
                return _raw(data)
            n = int("".join(str(d) for d in nib[:-1]))
            neg = sign == 0xD
        elif item.usage == "COMP":
            n = int.from_bytes(data, "big", signed=pic.signed)
            neg = n < 0
            n = abs(n)
        elif item.usage == "COMP-5":
            n = int.from_bytes(data, "little", signed=pic.signed)
            neg = n < 0
            n = abs(n)
        else:
            return _raw(data)
    except (IndexError, ValueError):
        return _raw(data)
    value = from_scaled(-n if neg else n, pic)
    text = canonical_text(value, pic.scale)
    return ("-" + text) if neg and n == 0 else text


def _raw(data: bytes) -> str:
    return "raw:" + data.hex()


def decode_record(record: DataItem, data: bytes) -> list[tuple[DataItem, str]]:
    out: list[tuple[DataItem, str]] = []
    data = data.ljust(record.size, b" ")

    def walk(item: DataItem, shift: int) -> None:
        # offsets of items under an OCCURS refer to its first occurrence; `shift` adds k*unit_size
        if item.redefines or item.level in (66, 88):
            return
        for occ in range(item.occurs or 1):
            s = shift + occ * item.unit_size
            if item.children:
                for c in item.children:
                    walk(c, s)
            elif not item.is_filler:
                start = item.offset - record.offset + s
                out.append((item, decode_elementary(item, data[start : start + item.unit_size])))

    if record.children:
        for c in record.children:
            walk(c, 0)
    elif not record.is_filler:
        out.append((record, decode_elementary(record, data[: record.size])))
    return out


def display_value(item: DataItem, shown: str) -> str:
    """Normalise a DISPLAYed numeric (`+00123.45`, `007-`) to canonical text."""
    s = shown.strip()
    if item.pic is None or item.pic.category != "numeric":
        return shown
    neg = s.startswith("-") or s.endswith("-")
    body = s.strip("+-")
    try:
        d = Decimal(body) if body else Decimal(0)
    except InvalidOperation:
        return shown
    text = canonical_text(d, max(item.pic.scale, 0))
    return "-" + text if neg and d != 0 else text
