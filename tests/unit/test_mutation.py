from __future__ import annotations

from collections import Counter
from pathlib import Path

from verifier.mutation import CATEGORIES, apply_mutant, find_mutants, sample_mutants
from verifier.mutation.engine import nines_exp, pow10_exp

JAVA = """package corpus;
import java.math.BigDecimal;
import java.math.RoundingMode;
public class Calc {
    long wsTotal;
    long wsI;
    BigDecimal wsRate = BigDecimal.ZERO;
    void calcPara() {
        long exact = wsTotal * 15;
        wsTotal = ((exact + 5) / 10) % 100000;
        for (wsI = 1; wsI <= 3; wsI++) {
            wsTotal = wsTotal - 1;
        }
        if (wsTotal > 99999) {
            wsTotal = 0;
        } else {
            wsTotal = -wsTotal;
        }
        wsRate = wsRate.multiply(BigDecimal.TEN).setScale(2, RoundingMode.HALF_UP);
        String s = String.format("%-5s", "AB");
    }
}
"""

PY = """def calc_para(s):
    exact = s.ws_total * 15
    s.ws_total = ((exact + 5) // 10) % 100000
    for i in range(1, 4):
        s.ws_total = s.ws_total - 1
    if s.ws_total > 99999:
        s.ws_total = 0
    else:
        s.ws_total = -s.ws_total
    return f"{s.ws_name:<5}".ljust(5)
"""

GO = """package calc

func CalcPara(s *State) {
	exact := s.WsTotal * 15
	s.WsTotal = ((exact + 5) / 10) % 100000
	for i := 1; i <= 3; i++ {
		s.WsTotal = s.WsTotal - 1
	}
	if s.WsTotal > 99999 {
		s.WsTotal = 0
	} else {
		s.WsTotal = -s.WsTotal
	}
}
"""


def _write(tmp: Path, name: str, text: str) -> Path:
    root = tmp / "repo"
    (root / Path(name).parent).mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, "utf-8")
    return root


def test_helpers() -> None:
    assert pow10_exp(1000) == 3 and pow10_exp(10) == 1 and pow10_exp(1) is None and pow10_exp(1001) is None
    assert nines_exp(999) == 3 and nines_exp(998) is None


def test_java_operators_cover_every_category(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/Calc.java", JAVA)
    ms = find_mutants(root, "java")
    cats = Counter(m.category for m in ms)
    assert set(cats) == set(CATEGORIES), cats
    ops = {m.operator for m in ms}
    assert {"ROUNDING_DROPPED", "ROUNDING_HALF_EVEN", "TRUNCATION_REMOVED", "TRUNCATION_WIDER", "SIGN_DROPPED",
            "SCALE_SHIFT", "LOOP_BOUND_OFF_BY_ONE", "COMPARISON_FLIP", "PAD_WRONG_SIDE", "SIZE_ERROR_IGNORED",
            "DOUBLE_ARITHMETIC", "BRANCHES_SWAPPED"} <= ops
    loop = next(m for m in ms if m.operator == "LOOP_BOUND_OFF_BY_ONE")
    assert loop.original == "<=" and loop.replacement == "<"


def test_apply_mutant_edits_a_copy_exactly(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/Calc.java", JAVA)
    m = next(m for m in find_mutants(root, "java") if m.operator == "TRUNCATION_REMOVED")
    apply_mutant(root, m)
    text = (root / "src/Calc.java").read_text("utf-8")
    assert "% 100000" not in text and "((exact + 5) / 10)" in text


def test_line_ranges_restrict_sites(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/Calc.java", JAVA)
    ms = find_mutants(root, "java", line_ranges={"src/Calc.java": [(11, 13)]})
    assert ms and all(11 <= m.line <= 13 for m in ms)


def test_sample_is_deterministic_and_stratified(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/Calc.java", JAVA)
    ms = find_mutants(root, "java")
    a, b = sample_mutants(ms, 10, seed=7), sample_mutants(ms, 10, seed=7)
    assert [m.id for m in a] == [m.id for m in b]
    assert len({m.category for m in a}) == 10


def test_python_and_go_operators(tmp_path: Path) -> None:
    py = find_mutants(_write(tmp_path / "p", "calc.py", PY), "python")
    assert {"truncation", "rounding", "loop_bound", "comparison", "sign", "size_error", "branch_swap",
            "padding"} <= {m.category for m in py}
    go = find_mutants(_write(tmp_path / "g", "calc/calc.go", GO), "go")
    assert {"truncation", "rounding", "loop_bound", "comparison", "sign", "size_error",
            "branch_swap"} <= {m.category for m in go}
