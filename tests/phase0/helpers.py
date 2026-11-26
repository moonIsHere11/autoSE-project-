"""Build a StrictProgram from inline COBOL without Docker (text shaped like `cobc -E` output)."""

from __future__ import annotations

import hashlib

from phase0.schema import Unit
from phase0.stages.facts import ProgramBuilder, ProgramFacts
from phase0.stages.parse import StrictProgram, parse_one

from verifier.cobol.lexer import map_lines
from verifier.cobol.preprocess import Preprocessed


def strict(src: str, name: str = "T.cbl") -> StrictProgram:
    lines = src.strip("\n").splitlines()
    text = f'#line 1 "{name}"\n' + "\n".join(" " + ln[7:] if len(ln) > 7 else "" for ln in lines)
    pre = Preprocessed(name, text, map_lines(text, name), "fixed", [], hashlib.sha256(text.encode()).hexdigest(), True, "")
    parsed = parse_one(name, pre)
    assert not isinstance(parsed, type(None)) and isinstance(parsed, list), parsed
    return parsed[0]


def facts(src: str) -> ProgramFacts:
    return ProgramBuilder(strict(src), multi=False).build()


def unit(f: ProgramFacts, uid: str) -> Unit:
    return next(u for u in f.units if u.unit_id == uid)
