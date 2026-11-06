"""Tokenizer for `cobc -E` output (see spike S1 for the exact format).

`cobc -E` emits one line per source line, prefixed by a space, with `#line N "file"` markers that
map lines back to the original files, continuation lines already joined and COPY books expanded.
Every token keeps the original (file, line, column) for feedback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WORD = "WORD"
NUM = "NUM"
STR = "STR"
HEX = "HEX"
PIC = "PIC"
OP = "OP"
PERIOD = "PERIOD"
OTHER = "OTHER"

_WS = " \t\r\f"


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    file: str
    line: int
    col: int
    value: str = ""  # decoded literal value (STR/HEX)

    @property
    def up(self) -> str:
        return self.text.upper()

    def is_word(self, *words: str) -> bool:
        return self.kind == WORD and self.text.upper() in words

    def __repr__(self) -> str:
        return f"{self.kind}:{self.text}@{self.line}"


@dataclass(frozen=True)
class SourceLine:
    file: str
    line: int
    text: str


class LexError(ValueError):
    pass


_LINE_MARK = re.compile(r'^#line\s+(\d+)\s+"(.*)"\s*$')
_NUM = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)")
_WORD = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?")
_IS = re.compile(r"IS(?=[ \t]|$)", re.IGNORECASE)
_OPS = ("**", ">=", "<=", "<>", "=", ">", "<", "+", "-", "*", "/", "(", ")", ":", "&")
_NUM_END = _WS + ".,;):"


def map_lines(preprocessed: str, default_file: str) -> list[SourceLine]:
    """Turn `cobc -E` text into lines tagged with their original (file, line)."""
    out: list[SourceLine] = []
    cur_file, cur_line = default_file, 1
    for raw in preprocessed.splitlines():
        m = _LINE_MARK.match(raw)
        if m:
            cur_line, cur_file = int(m.group(1)), m.group(2)
            continue
        if raw.startswith("#"):
            continue
        out.append(SourceLine(cur_file, cur_line, raw))
        cur_line += 1
    return out


def _read_literal(text: str, i: int, sl: SourceLine) -> tuple[str, str, int, bool]:
    """Return (raw, value, end_index, is_hex) for a literal starting at i (optional prefix)."""
    start = i
    prefix = ""
    if text[i] not in "\"'":
        prefix = text[i].upper()
        i += 1
    q = text[i]
    j = i + 1
    buf: list[str] = []
    while j < len(text):
        if text[j] == q:
            if j + 1 < len(text) and text[j + 1] == q:
                buf.append(q)
                j += 2
                continue
            break
        buf.append(text[j])
        j += 1
    if j >= len(text):
        raise LexError(f"{sl.file}:{sl.line}: unterminated literal")
    value = "".join(buf)
    if prefix == "X":
        try:
            value = bytes.fromhex(value).decode("latin-1")
        except ValueError as exc:
            raise LexError(f"{sl.file}:{sl.line}: bad hex literal") from exc
    return text[start : j + 1], value, j + 1, prefix == "X"


def tokenize(lines: list[SourceLine]) -> list[Token]:
    toks: list[Token] = []
    pending_pic = False
    for sl in lines:
        text, n, i = sl.text, len(sl.text), 0
        while i < n:
            c = text[i]
            if c in _WS:
                i += 1
                continue
            if text.startswith("*>", i):
                break
            if c in ",;" and (i + 1 >= n or text[i + 1] in _WS):
                i += 1
                continue
            col = i + 1
            if pending_pic:
                m = _IS.match(text, i)
                if m:
                    toks.append(Token(WORD, m.group(0), sl.file, sl.line, col))
                    i = m.end()
                    continue
                j = i
                while j < n and text[j] not in _WS:
                    j += 1
                chunk, period = text[i:j], False
                if chunk.endswith("."):
                    chunk, period = chunk[:-1], True
                elif chunk.endswith((",", ";")):
                    chunk = chunk[:-1]
                toks.append(Token(PIC, chunk, sl.file, sl.line, col))
                if period:
                    toks.append(Token(PERIOD, ".", sl.file, sl.line, col + len(chunk)))
                pending_pic = False
                i = j
                continue
            if c in "\"'" or (c.upper() in "XZNB" and i + 1 < n and text[i + 1] in "\"'"):
                raw, value, i, is_hex = _read_literal(text, i, sl)
                toks.append(Token(HEX if is_hex else STR, raw, sl.file, sl.line, col, value))
                continue
            if c == "." and (i + 1 >= n or text[i + 1] in _WS):
                toks.append(Token(PERIOD, ".", sl.file, sl.line, col))
                i += 1
                continue
            m = _NUM.match(text, i)
            if m and (m.end() >= n or text[m.end()] in _NUM_END):
                toks.append(Token(NUM, m.group(0), sl.file, sl.line, col))
                i = m.end()
                continue
            m = _WORD.match(text, i)
            if m:
                w = m.group(0)
                toks.append(Token(NUM if w.isdigit() else WORD, w, sl.file, sl.line, col))
                if w.upper() in ("PIC", "PICTURE"):
                    pending_pic = True
                i = m.end()
                continue
            for op in _OPS:
                if text.startswith(op, i):
                    toks.append(Token(OP, op, sl.file, sl.line, col))
                    i += len(op)
                    break
            else:
                toks.append(Token(OTHER, c, sl.file, sl.line, col))
                i += 1
    return toks
