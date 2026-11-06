"""Translation manifest (docs/INTERFACE.md section 2): strict model + naming conventions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ManifestError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Declared(_Strict):
    kind: Literal["decimal", "alnum", "alpha", "group", "binary"]
    digits: int | None = None
    scale: int | None = None
    signed: bool | None = None
    usage: Literal["DISPLAY", "COMP", "BINARY", "COMP-3", "PACKED-DECIMAL", "COMP-5"] | None = None
    length: int | None = None

    @model_validator(mode="after")
    def _complete(self) -> Declared:
        if self.kind in ("decimal", "binary") and (self.digits is None or self.scale is None):
            raise ValueError(f"declared kind '{self.kind}' needs 'digits' and 'scale'")
        if self.kind in ("alnum", "alpha") and self.length is None:
            raise ValueError(f"declared kind '{self.kind}' needs 'length'")
        return self


class FieldMap(_Strict):
    cobol: str
    target: str
    declared: Declared | None = None
    target_type: str | None = None


class UnitMap(_Strict):
    cobol_paragraph: str
    target_symbol: str


class FileMap(_Strict):
    cobol_select: str
    path: str


class RunSpec(_Strict):
    command: str


class BuildSpec(_Strict):
    command: str
    workdir: str = "."


class ProgramMap(_Strict):
    cobol_program_id: str
    cobol_file: str | None = None
    run: RunSpec | None = None
    files: list[FileMap] = Field(default_factory=list)
    class_: str | None = Field(default=None, alias="class")
    module: str | None = None
    package: str | None = None
    units: list[UnitMap] = Field(default_factory=list)
    fields: list[FieldMap] = Field(default_factory=list)


class Manifest(_Strict):
    schema_version: Literal["1.0"]
    language: Literal["java", "python", "go"]
    build: BuildSpec | None = None
    programs: list[ProgramMap] = Field(default_factory=list)

    def program(self, program_id: str) -> ProgramMap | None:
        for p in self.programs:
            if p.cobol_program_id.upper() == program_id.upper():
                return p
        return None


def load_manifest(path: str | Path, lang: str) -> Manifest:
    try:
        raw = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    try:
        m = Manifest.model_validate(raw)
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            lines.append(f"  - {loc or '<root>'}: {err['msg']}")
        raise ManifestError(f"invalid manifest {path}:\n" + "\n".join(lines)) from exc
    if m.language != lang:
        raise ManifestError(f"manifest language '{m.language}' does not match --lang {lang}")
    return m


# ---------------------------------------------------------------------------------------------
# naming conventions
# ---------------------------------------------------------------------------------------------
def _parts(name: str) -> list[str]:
    return [p for p in re.split(r"[-_\s]+", name.strip()) if p]


def camel(name: str) -> str:
    ps = [p.lower() for p in _parts(name)]
    if not ps:
        return name
    out = ps[0] + "".join(p[:1].upper() + p[1:] for p in ps[1:])
    return f"_{out}" if out[0].isdigit() else out


def pascal(name: str) -> str:
    out = "".join(p[:1].upper() + p[1:].lower() for p in _parts(name))
    return f"P{out}" if out and out[0].isdigit() else out


def snake(name: str) -> str:
    out = "_".join(p.lower() for p in _parts(name))
    return f"_{out}" if out and out[0].isdigit() else out


def loose(name: str) -> str:
    """Key for lenient matching: case-insensitive, separators removed."""
    return re.sub(r"[-_\s]", "", name).lower()


def conventional_symbol(lang: str, cobol_name: str, kind: Literal["program", "paragraph", "field"]) -> str:
    if lang == "java":
        return pascal(cobol_name) if kind == "program" else camel(cobol_name)
    if lang == "python":
        return snake(cobol_name)
    return pascal(cobol_name)
