"""Python language pack: indexing, resolution, diagnostics parsing and static rules (no Docker)."""

from __future__ import annotations

from pathlib import Path

from verifier.cobol.lexer import map_lines, tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.syntax import Program
from verifier.config import VerifierConfig
from verifier.langpacks.base import PackContext
from verifier.langpacks.python.pack import (
    PySymbolIndex,
    PythonPack,
    module_name,
    parse_diagnostics,
    parse_python_dependencies,
    py_type_base,
)
from verifier.manifest import Manifest
from verifier.sandbox.docker_runner import DockerRunner
from verifier.tiers.t0_static import StaticInput, run_t0b

COBOL = """
IDENTIFICATION DIVISION.
PROGRAM-ID. PAYCALC.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
SELECT OUT-FILE ASSIGN TO "PAY.OUT" ORGANIZATION IS LINE SEQUENTIAL.
DATA DIVISION.
FILE SECTION.
FD OUT-FILE.
01 OUT-REC PIC X(20).
WORKING-STORAGE SECTION.
01 WS-RATE PIC 9(3)V99 VALUE 0.
01 WS-HOURS PIC 9(3) VALUE 0.
01 WS-TOTAL PIC S9(7)V99 VALUE 0.
01 WS-NAME PIC X(10).
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM CALC-PAY
    STOP RUN.
CALC-PAY.
    COMPUTE WS-TOTAL ROUNDED = WS-RATE * WS-HOURS.
REPORT-PARA.
    DISPLAY WS-TOTAL.
"""

GOOD = '''"""Docstring mentioning corpus/x and 12345 must not count as literals."""
from __future__ import annotations

import sys
from decimal import Decimal
from dataclasses import dataclass


@dataclass
class Paycalc:
    ws_rate: int = 0
    ws_hours: "int" = 0

    def __init__(self) -> None:
        self.ws_total: Decimal = Decimal("0.00")
        self.ws_name = " " * 10
        self.ws_hours = 0

    def main_para(self) -> None:
        self.calc_pay()

    def calc_pay(self) -> None:
        self.ws_total = Decimal(self.ws_rate * self.ws_hours) / 100
        with open("PAY.OUT", "w") as f:
            f.write("x")
        n = -42


def report_para() -> None:
    sys.stdout.write("x")


if __name__ == "__main__":
    Paycalc().main_para()
'''

BAD = '''import os
import subprocess
import requests
from time import time as now
from datetime import datetime
import random

ws_total: float = 0.0
ws_name = 5


def main_para() -> None:
    try:
        t = now()
        d = datetime.now()
        r = random.randint(1, 6)
        os.system("ls")
        open("secret.txt")
        open("expected/stdout", "rb")
        x = eval("1+1")
    except:
        pass
    try:
        pass
    except Exception as e:
        raise
    try:
        pass
    except (ValueError, Exception):
        sys.exit(3)
    try:
        pass
    except BaseException:
        print("swallowed")


def calc_pay() -> None:
    pass


def report_para() -> None:
    pass
'''


def _program(src: str = COBOL) -> Program:
    text = '#line 1 "P.cbl"\n' + "\n".join(" " + ln.strip() for ln in src.strip().splitlines())
    progs = parse_source(tokenize(map_lines(text, "P.cbl")), "P.cbl")
    return progs[0]


def _ctx(root: Path, manifest: Manifest | None = None) -> PackContext:
    cfg = VerifierConfig()
    return PackContext(cfg, DockerRunner(cfg.image), root, manifest, None)


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
    return root


def _t0b(root: Path, manifest: Manifest | None = None) -> dict[str, list[tuple[str, str]]]:
    pack = PythonPack()
    idx = pack.index(root)
    prog = _program()
    rp = pack.resolve_program(_ctx(root, manifest), idx, prog, manifest.program(prog.program_id) if manifest else None)
    si = StaticInput("python", pack.static_rules(), idx, root, [(prog, rp)], set(), None, [])
    res = run_t0b(si)
    return {c.name: [(f.severity, f.message) for f in c.findings] for c in res.by_program["PAYCALC"]}


# ---------------------------------------------------------------------------------------------
def test_module_name_climbs_packages(tmp_path: Path) -> None:
    _write(tmp_path, {"src/app/__init__.py": "", "src/app/sub/__init__.py": "", "src/app/sub/prog.py": "",
                      "top.py": "", "pkg/__init__.py": "", "pkg/__main__.py": ""})
    assert module_name(tmp_path, "src/app/sub/prog.py") == ("app.sub.prog", "src")
    assert module_name(tmp_path, "top.py") == ("top", "")
    assert module_name(tmp_path, "pkg/__main__.py") == ("pkg", "")


def test_index_classes_fields_methods_and_uses(tmp_path: Path) -> None:
    _write(tmp_path, {"paycalc.py": GOOD, "tests/test_x.py": "import socket\n"})
    idx = PythonPack().index(tmp_path)
    assert isinstance(idx, PySymbolIndex)
    mod = idx.modules["paycalc.py"]
    assert mod.has_main_guard and mod.dotted == "paycalc"
    assert [f.name for f in mod.functions] == ["report_para"]
    cls = mod.classes[0]
    assert {m.name for m in cls.methods} >= {"__init__", "main_para", "calc_pay"}
    types = {f.name: f.type_text for f in cls.fields}
    assert types == {"ws_rate": "int", "ws_hours": "int", "ws_total": "Decimal", "ws_name": "str"}
    assert ("-42" in {lit.value for lit in idx.literals}) and "12345" not in {lit.value for lit in idx.literals}
    assert not any("corpus" in lit.value for lit in idx.literals)  # the docstring is not a literal
    opens = [c for c in idx.calls if c.callee == "open"]
    assert opens and opens[0].string_args == ["PAY.OUT"]  # only the path argument, not the mode
    assert "tests/test_x.py" in idx.files and all(i[1] != "tests/test_x.py" for i in idx.imports)


def test_index_canonicalises_aliases_and_catches(tmp_path: Path) -> None:
    _write(tmp_path, {"paycalc.py": BAD})
    idx = PythonPack().index(tmp_path)
    callees = {c.callee for c in idx.calls}
    assert {"time.time", "datetime.datetime.now", "random.randint", "os.system", "eval"} <= callees
    swallow = [(c.types, c.swallows) for c in idx.catches]
    assert (["bare except"], True) in swallow
    assert (["Exception"], False) in swallow  # re-raises
    assert (["ValueError", "Exception"], False) in swallow  # exits
    assert (["BaseException"], True) in swallow
    assert any(u[0] == "float" or "float" in u[0] for u in idx.float_uses)


def test_resolution_by_convention(tmp_path: Path) -> None:
    _write(tmp_path, {"src/app/__init__.py": "", "src/app/paycalc.py": GOOD})
    pack = PythonPack()
    rp = pack.resolve_program(_ctx(tmp_path), pack.index(tmp_path), _program(), None)
    assert rp.type_sym is not None and rp.type_sym.file == "src/app/paycalc.py"
    assert rp.run_command == "PYTHONPATH=/tgt/src:/tgt:/opt/cobolrt/python python3 -B -P -m app.paycalc"
    assert rp.units == {"MAIN-PARA": "main_para", "CALC-PAY": "calc_pay", "REPORT-PARA": "report_para"}
    assert rp.fields["WS-TOTAL"]["target"] == "ws_total" and rp.fields["WS-TOTAL"]["target_type"] == "Decimal"
    assert rp.files == {"OUT-FILE": "PAY.OUT"}
    cmd = pack.run_command(_ctx(tmp_path), rp)
    assert isinstance(cmd, list) and cmd[:2] == ["sh", "-c"]


def test_resolution_with_manifest(tmp_path: Path) -> None:
    _write(tmp_path, {"lib/payroll_impl.py": GOOD.replace("def calc_pay", "def compute")})
    m = Manifest.model_validate({
        "schema_version": "1.0", "language": "python",
        "programs": [{"cobol_program_id": "PAYCALC", "module": "lib.payroll_impl",
                      "run": {"command": "python3 lib/payroll_impl.py"},
                      "units": [{"cobol_paragraph": "CALC-PAY", "target_symbol": "Paycalc.compute"}],
                      "fields": [{"cobol": "WS-RATE", "target": "ws_rate", "target_type": "float"}]}]})
    pack = PythonPack()
    rp = pack.resolve_program(_ctx(tmp_path, m), pack.index(tmp_path), _program(), m.program("PAYCALC"))
    assert rp.type_sym is not None and rp.type_sym.file == "lib/payroll_impl.py"
    assert rp.run_command == "python3 /tgt/lib/payroll_impl.py"
    assert rp.units["CALC-PAY"] == "compute"
    assert rp.fields["WS-RATE"]["target_type"] == "float"


def test_missing_module_is_not_applicable(tmp_path: Path) -> None:
    _write(tmp_path, {"other.py": "x = 1\n"})
    pack = PythonPack()
    rp = pack.resolve_program(_ctx(tmp_path), pack.index(tmp_path), _program(), None)
    assert rp.type_sym is None and rp.run_command is None
    assert not isinstance(pack.run_command(_ctx(tmp_path), rp), list)


def test_parse_diagnostics_splits_compile_errors_and_mypy_warnings(tmp_path: Path) -> None:
    _write(tmp_path, {"a.py": "x = (\n", "b.py": "y: int = 'no'\n"})
    out = ("a.py:1: error: SyntaxError: '(' was never closed\npy_compile: 2 module(s), 1 with errors\n"
           "@@VERIFIER-MYPY@@\nmypy 2.4.0 (compiled: yes)\n"
           "b.py:1:10: error: Incompatible types in assignment  [assignment]\nb.py:1: note: something\n"
           "@@VERIFIER-MYPY-EXIT 1@@\n")
    ds = parse_diagnostics(out, tmp_path)
    assert [(d.check, d.severity, d.file, d.line) for d in ds] == [
        ("T0a.build", "ERROR", "a.py", 1), ("T0a.mypy", "WARNING", "b.py", 1)]
    assert ds[0].excerpt and ">" in ds[0].excerpt and ds[1].column == 10
    crashed = parse_diagnostics("@@VERIFIER-MYPY@@\nerror: Duplicate module named 'x'\n@@VERIFIER-MYPY-EXIT 2@@", tmp_path)
    assert crashed[0].severity == "WARNING" and "could not check" in crashed[0].message


def test_static_rules_clean_translation(tmp_path: Path) -> None:
    _write(tmp_path, {"paycalc.py": GOOD})
    res = _t0b(tmp_path)
    errors = [m for fs in res.values() for sev, m in fs if sev == "ERROR"]
    assert errors == [], errors


def test_static_rules_flag_forbidden_python(tmp_path: Path) -> None:
    _write(tmp_path, {"paycalc.py": BAD})
    res = _t0b(tmp_path)
    errs = {k: [m for sev, m in v if sev == "ERROR"] for k, v in res.items()}
    api = " | ".join(errs["forbidden_api"])
    for needle in ("time.time", "datetime.datetime.now", "random.randint", "os.system", "eval",
                   "import `subprocess`", "'secret.txt'", "bare except", "BaseException"):
        assert needle in api, (needle, api)
    assert "ValueError, Exception" not in api
    assert any("requests" in m for m in errs["integrity"])
    assert any("expected/stdout" in m for m in errs["integrity"])
    assert any("ws_total" in m and "floating point" in m for m in errs["forbidden_representation"])
    assert any("WS-NAME" in m and "numeric type" in m for m in errs["data_mapping"])


def test_type_base_and_dependencies() -> None:
    assert py_type_base("Optional[list[float]]") == "float"
    assert py_type_base("decimal.Decimal | None") == "Decimal"
    assert py_type_base("Final[int]") == "int"
    assert py_type_base("bytes") == "bytes"
    assert parse_python_dependencies("requests>=2\n# c\ncobolrt\n-r other.txt\n") == ["requests", "cobolrt"]
    assert parse_python_dependencies('[project]\ndependencies = ["numpy==1.0", "cobolrt"]\n') == ["numpy", "cobolrt"]
