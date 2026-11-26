"""Target side of the KB: toolchain, curated gap/rule catalogue, runtime library, driver template."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

from phase0.schema import Gap, Rule, Toolchain
from phase0.workspace import ContractError, RunConfig

REPO = Path(__file__).resolve().parents[2]
RUNTIME_SOURCES = {"java": REPO / "runtimes" / "java" / "src" / "cobolrt"}
DRIVER_TEMPLATES = {"java": "driver_java"}

# the project compiles every .java file together (runtime sources included) into a temp dir,
# so nothing is written inside the project that Phase 2 snapshots
JAVA_BUILD = 'out=$(mktemp -d) && javac -encoding ISO-8859-1 -d "$out" $(find . -name "*.java")'
# smoke test of the execution interface: an unknown unit must come back as status "error"
JAVA_TEST = JAVA_BUILD + ' && echo \'{"unit_id": "?", "state": {}}\' | java -cp "$out" app.Driver'


def toolchain(cfg: RunConfig) -> Toolchain:
    if cfg.language != "java":
        raise ContractError(f"target language {cfg.language!r} is not supported yet; supported: ['java']")
    base: dict[str, object] = {
        "language": "java",
        "version": cfg.version,
        "file_ext": ".java",
        "build_cmd": ["sh", "-c", JAVA_BUILD],
        "test_cmd": ["sh", "-c", JAVA_TEST],
        "lint_cmd": None,
        "runtime_dir": "cobolrt",
    }
    for key, value in cfg.target_overrides.items():
        if key in base:
            base[key] = value
    return Toolchain.model_validate(base)


def _catalog_text(name: str) -> str:
    return resources.files("phase0").joinpath("catalog", name).read_text("utf-8")


def load_gaps() -> list[Gap]:
    return [Gap.model_validate(g) for g in json.loads(_catalog_text("gaps.json"))]


def load_rules() -> list[Rule]:
    return [Rule.model_validate(r) for r in json.loads(_catalog_text("rules.json"))]


def copy_runtime(language: str, dest: Path) -> list[str]:
    """Byte-identical copy of the runtime library Phase 2 verifies; returns the copied relative paths."""
    src = RUNTIME_SOURCES[language]
    if not src.is_dir():
        raise ContractError(f"runtime sources missing at {src}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copied: list[str] = []
    for p in sorted(src.rglob("*.java")):
        rel = p.relative_to(src)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest / rel)
        copied.append(rel.as_posix())
    return copied


def _template(*parts: str) -> Path:
    return Path(str(resources.files("phase0").joinpath("templates", *parts)))


def copy_driver_template(language: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(_template(DRIVER_TEMPLATES[language]), dest)


def copy_encoding_fixtures(dest: Path) -> None:
    """Kept outside driver_template/: Phase 1 copies that directory into the project, and the
    verifier's T0 lint rejects project code that opens files the COBOL program does not declare."""
    shutil.copyfile(_template("encoding", "encoding_fixtures.json"), dest)
