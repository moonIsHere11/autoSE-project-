"""The COBOL semantics golden suite (spec section 9).

* `test_interpreter_matches_golden` runs the IR interpreter on every golden program (from the
  stored `cobc -E` text, no Docker needed) and compares stdout, files and return code byte for byte
  with the outputs captured from GnuCOBOL by tools/capture_semantics.py.
* `test_gnucobol_matches_golden` (docker) re-runs GnuCOBOL and checks the stored goldens still hold.
"""

from __future__ import annotations

import pytest

from tools.capture_semantics import EXPECTED, case_for, load_expected, program_names, run_goldens
from verifier.cobol.interp import run_program
from verifier.cobol.ir import lower_program
from verifier.cobol.lexer import map_lines, tokenize
from verifier.cobol.parser import parse_source
from verifier.config import VerifierConfig
from verifier.sandbox.docker_runner import DockerRunner

NAMES = program_names()


def test_every_program_has_a_golden() -> None:
    missing = [n for n in NAMES if not (EXPECTED / n / "stdout").exists()]
    assert not missing, f"run `python -m tools.capture_semantics {' '.join(missing)}`"


def test_suite_covers_spec_features() -> None:
    required = {"MOVENUM", "MOVEALN", "MOVEMIX", "ROUNDING", "PRECISN", "SIZEERR", "DIVREM", "NEGZERO",
                "BINTRUNC", "REDEF", "OCCURS", "VARYING", "FALLTHRU", "EVALUATE", "LEVEL88", "INITLZ",
                "DISPSGN", "FILESTAT"}
    assert required <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_interpreter_matches_golden(name: str) -> None:
    g = load_expected(name)
    prog = parse_source(tokenize(map_lines(g.preprocessed, f"{name}.cbl")), f"{name}.cbl")[0]
    ir = lower_program(prog)
    assert ir.interpretability() is None
    spec = case_for(name)
    res = run_program(ir, spec.stdin, {f.name: f.data for f in spec.files_in})
    assert res.runtime_error is None
    assert res.stdout == g.stdout
    assert res.return_code == g.return_code
    assert res.files == g.files


@pytest.mark.docker
@pytest.mark.slow
def test_gnucobol_matches_golden(runner: DockerRunner, config: VerifierConfig) -> None:
    fresh = run_goldens(NAMES, runner, config)
    for name in NAMES:
        g = load_expected(name)
        f = fresh[name]
        assert (f.stdout, f.return_code, f.files) == (g.stdout, g.return_code, g.files), name
