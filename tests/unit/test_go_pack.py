"""Go language pack: indexing, resolution, diagnostics parsing and static rules (no Docker)."""

from __future__ import annotations

from pathlib import Path

from verifier.cobol.lexer import map_lines, tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.syntax import Program
from verifier.config import VerifierConfig
from verifier.langpacks.base import PackContext
from verifier.langpacks.go.pack import (
    GoPack,
    GoSymbolIndex,
    bin_name,
    go_type_base,
    parse_diagnostics,
    parse_go_dependencies,
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
01 WS-TOTAL PIC S9(11)V99 VALUE 0.
01 WS-NAME PIC X(10).
01 WS-COUNTS.
   05 WS-COUNT PIC 9(5) OCCURS 3 TIMES.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM CALC-PAY
    STOP RUN.
CALC-PAY.
    COMPUTE WS-TOTAL ROUNDED = WS-RATE * WS-HOURS.
REPORT-PARA.
    DISPLAY WS-TOTAL.
"""

GOOD = """package main

import (
\t"bufio"
\t"os"
\t"strings"
)

// Paycalc holds the state.
type Paycalc struct {
\tWsRate   int64
\tWsHours  int64
\tWsTotal  int64
\tWsName   string
\tWsCount  [3]int64
}

var WsSpare = 0

func (p *Paycalc) MainPara() { p.CalcPay() }

func (p *Paycalc) CalcPay() {
\tp.WsTotal = p.WsRate * p.WsHours
\tos.WriteFile("PAY.OUT", []byte(strings.Repeat(" ", 3)), 0o644)
\tn := -42
\t_ = n
}

// ReportPara is REPORT-PARA.
func ReportPara() {
\tw := bufio.NewWriter(os.Stdout)
\tw.Flush()
}

func main() {
\tp := &Paycalc{}
\tp.MainPara()
}
"""

BAD = """package main

import (
\t"fmt"
\tex "os/exec"
\t"math/rand"
\t"net/http"
\t"os"
\t"time"
\t"github.com/shopspring/decimal"
)

type Paycalc struct {
\tWsRate  float64
\tWsTotal int32
\tWsName  int
\tWsCount [3]int16
}

func (p *Paycalc) MainPara() {
\tdefer func() {
\t\tif r := recover(); r != nil {
\t\t\tfmt.Println("ignored")
\t\t}
\t}()
\tdefer func() {
\t\tif r := recover(); r != nil {
\t\t\tpanic(r)
\t\t}
\t}()
\t_ = time.Now()
\t_ = rand.Intn(3)
\tex.Command("ls")
\thttp.Get("x")
\tos.Open("secret.txt")
\tos.ReadFile("expected/stdout")
\t_ = decimal.Zero
}

func (p *Paycalc) CalcPay() {}

func ReportPara() {}

func main() {}
"""


def _program() -> Program:
    text = '#line 1 "P.cbl"\n' + "\n".join(" " + ln.strip() for ln in COBOL.strip().splitlines())
    return parse_source(tokenize(map_lines(text, "P.cbl")), "P.cbl")[0]


def _ctx(root: Path, manifest: Manifest | None = None) -> PackContext:
    cfg = VerifierConfig()
    return PackContext(cfg, DockerRunner(cfg.image), root, manifest, None)


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
    return root


def _t0b(root: Path) -> dict[str, list[tuple[str, str]]]:
    pack = GoPack()
    idx = pack.index(root)
    prog = _program()
    rp = pack.resolve_program(_ctx(root), idx, prog, None)
    deps = {"go.mod": (root / "go.mod").read_text()} if (root / "go.mod").exists() else {}
    si = StaticInput("go", pack.static_rules(), idx, root, [(prog, rp)], set(), None, [], deps)
    res = run_t0b(si)
    return {c.name: [(f.severity, f.message) for f in c.findings] for c in res.by_program["PAYCALC"]}


# ---------------------------------------------------------------------------------------------
def test_index_packages_structs_and_uses(tmp_path: Path) -> None:
    _write(tmp_path, {"go.mod": "module example.com/pay\n\ngo 1.22\n", "paycalc/main.go": GOOD,
                      "paycalc/main_test.go": "package main\n", "lib/util.go": "package lib\n\nfunc Helper() {}\n"})
    idx = GoPack().index(tmp_path)
    assert isinstance(idx, GoSymbolIndex)
    assert idx.module_dirs == [""]
    pkg = idx.packages["paycalc"]
    assert pkg.has_main and pkg.main_file == "paycalc/main.go" and pkg.files == ["paycalc/main.go"]
    assert not idx.packages["lib"].has_main
    st = pkg.structs[0]
    assert st.name == "Paycalc" and {m.name for m in st.methods} == {"MainPara", "CalcPay"}
    assert {f.name: f.type_text for f in st.fields}["WsCount"] == "[3]int64"
    assert [(v.name, v.type_text) for v in pkg.vars] == [("WsSpare", "int")]
    assert {f.name for f in pkg.funcs} == {"ReportPara", "main"}
    assert "-42" in {lit.value for lit in idx.literals}
    wf = next(c for c in idx.calls if c.callee == "os.WriteFile")
    assert wf.string_args == ["PAY.OUT"]


def test_resolution_conventions_and_root_fallback(tmp_path: Path) -> None:
    _write(tmp_path / "a", {"go.mod": "module example.com/pay\n", "paycalc/main.go": GOOD})
    pack = GoPack()
    rp = pack.resolve_program(_ctx(tmp_path / "a"), pack.index(tmp_path / "a"), _program(), None)
    assert rp.run_command == "/tgt/.verifier-build/bin/paycalc"
    assert rp.units == {"MAIN-PARA": "MainPara", "CALC-PAY": "CalcPay", "REPORT-PARA": "ReportPara"}
    assert rp.fields["WS-TOTAL"]["target"] == "WsTotal" and rp.fields["WS-COUNT"]["target_type"] == "[3]int64"
    assert not rp.notes
    # a single-program repository without go.mod: the root main package is used, and noted
    _write(tmp_path / "b", {"main.go": GOOD})
    rp2 = pack.resolve_program(_ctx(tmp_path / "b"), pack.index(tmp_path / "b"), _program(), None)
    assert rp2.run_command == "/tgt/.verifier-build/bin/_root"
    assert any("no go.mod" in n for n in rp2.notes) and any("root main package" in n for n in rp2.notes)
    # nothing that looks like the program
    _write(tmp_path / "c", {"go.mod": "module x\n", "a/main.go": GOOD, "b/main.go": GOOD})
    rp3 = pack.resolve_program(_ctx(tmp_path / "c"), pack.index(tmp_path / "c"), _program(), None)
    assert rp3.run_command is None and not isinstance(pack.run_command(_ctx(tmp_path / "c"), rp3), list)


def test_resolution_with_manifest(tmp_path: Path) -> None:
    _write(tmp_path, {"go.mod": "module x\n", "cmd/pay/main.go": GOOD.replace("CalcPay", "Compute")})
    m = Manifest.model_validate({
        "schema_version": "1.0", "language": "go",
        "programs": [{"cobol_program_id": "PAYCALC", "package": "cmd/pay", "class": "Paycalc",
                      "units": [{"cobol_paragraph": "CALC-PAY", "target_symbol": "Paycalc.Compute"}]}]})
    pack = GoPack()
    rp = pack.resolve_program(_ctx(tmp_path, m), pack.index(tmp_path), _program(), m.program("PAYCALC"))
    assert rp.run_command == "/tgt/.verifier-build/bin/cmd__pay" and rp.units["CALC-PAY"] == "Compute"
    assert rp.source == "mixed"


def test_bin_name_and_type_base() -> None:
    assert bin_name("") == "_root" and bin_name("cmd/pay") == "cmd__pay"
    assert go_type_base("[4]int64") == "int64"
    assert go_type_base("[]float64") == "float64"
    assert go_type_base("[10]byte") == "[]byte"
    assert go_type_base("*big.Int") == "Int"
    assert go_type_base("decimal.Decimal") == "Decimal"


def test_parse_diagnostics_maps_files_and_splits_vet(tmp_path: Path) -> None:
    _write(tmp_path, {"go.mod": "module x\n", "pay/main.go": "package main\n\nfunc main() {\n\tx := 1\n}\n"})
    out = ("go version go1.22.12 linux/amd64\n# x/pay\npay/main.go:4:2: declared and not used: x\n"
           "@@VERIFIER-VET@@\n# x/pay\nvet: pay/main.go:3:1: something odd\n@@VERIFIER-VET-EXIT 1@@\n")
    ds = parse_diagnostics(out, tmp_path, [""])
    assert [(d.check, d.severity, d.file, d.line, d.column) for d in ds] == [
        ("T0a.build", "ERROR", "pay/main.go", 4, 2), ("T0a.vet", "WARNING", "pay/main.go", 3, 1)]
    assert ds[0].excerpt and ">    4 |" in ds[0].excerpt
    # paths relative to a nested module directory are mapped back to the repo
    _write(tmp_path / "n", {"svc/go.mod": "module y\n", "svc/main.go": "package main\n"})
    ds2 = parse_diagnostics("./main.go:1:1: oops\n", tmp_path / "n", ["svc"])
    assert ds2[0].file == "svc/main.go"


def test_dependencies_parser() -> None:
    gm = "module a\n\ngo 1.22\n\nrequire github.com/x/y v1.0.0\nrequire (\n\tcobolrt v0.0.0 // rt\n\tgolang.org/z v1\n)\n"
    assert parse_go_dependencies(gm) == ["github.com/x/y", "cobolrt", "golang.org/z"]
    assert parse_go_dependencies("requests==1\n") == []


def test_static_rules_clean_translation(tmp_path: Path) -> None:
    _write(tmp_path, {"go.mod": "module example.com/pay\n\ngo 1.22\n", "paycalc/main.go": GOOD})
    res = _t0b(tmp_path)
    errors = [m for fs in res.values() for sev, m in fs if sev == "ERROR"]
    assert errors == [], errors


def test_static_rules_flag_forbidden_go(tmp_path: Path) -> None:
    _write(tmp_path, {"go.mod": "module example.com/pay\n\ngo 1.22\n\nrequire github.com/shopspring/decimal v1.3.1\n",
                      "paycalc/main.go": BAD})
    res = _t0b(tmp_path)
    errs = {k: [m for sev, m in v if sev == "ERROR"] for k, v in res.items()}
    api = " | ".join(errs["forbidden_api"])
    for needle in ("time.Now", "math/rand.Intn", "os/exec.Command", "net/http.Get", "import `os/exec`",
                   "import `net/http`", "'secret.txt'", "recover()"):
        assert needle in api, (needle, api)
    assert sum("recover()" in m for m in errs["forbidden_api"]) == 1  # the re-panicking one is fine
    integ = " | ".join(errs["integrity"])
    assert "github.com/shopspring/decimal" in integ and "expected/stdout" in integ
    rep = " | ".join(errs["forbidden_representation"])
    assert "WS-RATE" in rep and "float64" in rep
    assert "int32" in rep and "13 digits" in rep  # WS-TOTAL S9(11)V99 in int32
    assert "int16" in rep and "WS-COUNT" in rep  # 5 digits in int16 (element type of the OCCURS)
    assert any("WS-NAME" in m for m in errs["data_mapping"])


def test_go_padding_mutant(tmp_path: Path) -> None:
    from verifier.mutation import apply_mutant, find_mutants

    src = 'package main\n\nimport "strings"\n\nfunc pad(s string, n int) string {\n\treturn s + strings.Repeat(" ", n-len(s))\n}\n'
    _write(tmp_path, {"p/main.go": src})
    ms = [m for m in find_mutants(tmp_path, "go") if m.category == "padding"]
    assert len(ms) == 1
    apply_mutant(tmp_path, ms[0])
    assert 'return strings.Repeat(" ", n-len(s)) + s' in (tmp_path / "p/main.go").read_text()
