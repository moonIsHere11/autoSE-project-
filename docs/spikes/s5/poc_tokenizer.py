"""Spike S5 proof-of-concept: tokenizer for `cobc -E` (GnuCOBOL 3.2) output.

Not production code. Grounds the effort estimate for a hand-written subset parser.
Usage:  python3 poc_tokenizer.py out/arith.E.cob [--dump]
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass

LINE_DIRECTIVE = re.compile(r'^#line (\d+) "((?:[^"\\]|\\.)*)"\s*$')

# Order matters. Literals and PIC strings are handled before the generic patterns.
TOKEN_RE = re.compile(
    r"""
    (?P<ws>[ \t]+)
  | (?P<alnum>(?:[XxZzNnGgBb]|[Nn][Xx])?(?:'(?:[^']|'')*'|"(?:[^"]|"")*"))   # X'..', 'it''s'
  | (?P<unterminated>['"].*)                                                # error case
  | (?P<number>[+-]?(?:\d*\.\d+|\d+)(?![A-Za-z0-9_-]))                       # 12.5 .075 -7 990
  | (?P<word>[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)                   # WS-AMT 0000-MAIN
  | (?P<period>\.(?=[ \t]|$))                                               # sentence end
  | (?P<sep>[,;](?=[ \t]|$))                                                # separators (cobc -E drops them)
  | (?P<op>\*\*|>=|<=|<>|[-+*/=<>():&])
  | (?P<other>\S)
    """,
    re.VERBOSE,
)
PIC_KEYWORDS = {"PIC", "PICTURE"}


@dataclass(frozen=True)
class Token:
    kind: str     # word | number | alnum | pic | period | op | error
    text: str     # words upper-cased; literals verbatim (quotes kept)
    file: str     # original source file (from #line)
    line: int     # line in that original file
    col: int      # 1-based column in the *-E output line* (NOT the original column)


def tokenize(lines: list[str]) -> list[Token]:
    toks: list[Token] = []
    file, line = "<unknown>", 0
    pic_pending = False  # previous significant token was PIC / PICTURE [IS]
    for raw in lines:
        raw = raw.rstrip("\r\n")
        m = LINE_DIRECTIVE.match(raw)
        if m:
            file, line = m.group(2), int(m.group(1))
            continue
        if raw.startswith("#"):
            toks.append(Token("error", raw, file, line, 1))
            line += 1
            continue
        pos = 0
        while pos < len(raw):
            if pic_pending and raw[pos] not in " \t":
                # PIC string: maximal non-blank run; a trailing '.' (or ',' / ';')
                # followed by blank/EOL is a separator, not part of the picture.
                end = pos
                while end < len(raw) and raw[end] not in " \t":
                    end += 1
                text = raw[pos:end]
                if text.upper() == "IS":
                    toks.append(Token("word", "IS", file, line, pos + 1))
                    pos = end
                    continue
                if text[-1] in ".,;" and len(text) > 1:
                    end -= 1
                    text = text[:-1]
                toks.append(Token("pic", text, file, line, pos + 1))
                pic_pending = False
                pos = end
                continue
            m = TOKEN_RE.match(raw, pos)
            assert m is not None
            kind, text = m.lastgroup, m.group()
            pos = m.end()
            if kind in ("ws", "sep"):
                continue
            if kind == "word":
                text = text.upper()
                if text.isdigit():
                    kind = "number"
                elif text in PIC_KEYWORDS:
                    pic_pending = True
            elif kind in ("unterminated", "other"):
                kind = "error"
            toks.append(Token(kind, text, file, line, m.start() + 1))
        line += 1
    return toks


def main(argv: list[str]) -> int:
    with open(argv[1], encoding="utf-8") as fh:
        toks = tokenize(fh.readlines())
    print(f"{argv[1]}: {len(toks)} tokens; kinds={dict(Counter(t.kind for t in toks))}")
    for t in toks:
        if t.kind in ("pic", "alnum", "error") or (t.kind == "number" and "." in t.text):
            print(f"  {t.file}:{t.line}:{t.col}  {t.kind:6} {t.text}")
    if "--dump" in argv:
        for t in toks:
            print(f"{t.file}:{t.line}:{t.col}\t{t.kind}\t{t.text}")
    # sentences / periods per line: a quick sanity check of line attribution
    return 1 if any(t.kind == "error" for t in toks) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
