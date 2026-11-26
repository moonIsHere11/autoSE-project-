from __future__ import annotations

import filecmp
import json
from decimal import Decimal
from pathlib import Path

from phase0.target import RUNTIME_SOURCES, _template, copy_runtime, toolchain
from phase0.workspace import RunConfig

from verifier.inputs.encode import canonical_text

REPO = Path(__file__).resolve().parents[2]


def cfg() -> RunConfig:
    return RunConfig(run_id=None, entry=None, dialect="default", compile_flags=[], language="java", version="21")


def test_runtime_is_byte_identical(tmp_path: Path) -> None:
    """The comparison Phase 2's adapter makes (filecmp.dircmp of runtime_dir vs kb/target/runtime)."""
    copied = copy_runtime("java", tmp_path / "rt")
    assert len(copied) >= 10
    cmp = filecmp.dircmp(RUNTIME_SOURCES["java"], tmp_path / "rt")
    assert cmp.left_only == [] and cmp.right_only == [] and cmp.diff_files == []
    for rel in copied:
        assert (RUNTIME_SOURCES["java"] / rel).read_bytes() == (tmp_path / "rt" / rel).read_bytes()


def test_toolchain_defaults_and_overrides() -> None:
    tc = toolchain(cfg())
    assert tc.runtime_dir == "cobolrt" and tc.file_ext == ".java"
    c = cfg()
    c.target_overrides = {"runtime_dir": "rt", "ignored_key": 1}
    assert toolchain(c).runtime_dir == "rt"


def test_driver_template_has_no_file_io() -> None:
    """The verifier's T0 lint rejects project code that opens undeclared files (found in e2e)."""
    for p in _template("driver_java").rglob("*.java"):
        text = p.read_text("utf-8")
        for banned in ("java.nio.file", "FileInputStream", "FileReader", "Paths.get"):
            assert banned not in text, (p.name, banned)


def test_encoding_fixtures_match_verifier() -> None:
    fx = json.loads(_template("encoding", "encoding_fixtures.json").read_text("utf-8"))
    for case in fx["decimal"]:
        value = Decimal(case["unscaled"]).scaleb(-case["scale"])
        text = canonical_text(value, case["scale"])
        if case["negative_zero"]:
            text = "-" + text
        assert text == case["canonical"], case["case"]
    for case in fx["alnum"]:
        assert case["value"][: case["length"]].ljust(case["length"]) == case["canonical"]
    for case in fx["group"]:
        assert bytes.fromhex(case["bytes_hex"]).decode("latin-1") == case["canonical"]
