"""Go language pack: build (go build + go vet), tree-sitter index, resolution, run command.

Conventions (docs/INTERFACE.md section 2): program → package directory `snake_case(PROGRAM-ID)`
holding `package main` with `func main` (or the repository root when it is the only main package),
built to one binary `/tgt/.verifier-build/bin/<dir>`; paragraph → exported `PascalCase` function or
method; field → exported `PascalCase` struct field or package variable.

The build runs inside the sandbox with no network: `GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off
CGO_ENABLED=0`, with GOCACHE/GOPATH inside the workspace copy. A target without `go.mod` gets one
created **in the workspace copy only** (module `verifier.local/target`), recorded in the notes.
"""

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from tree_sitter import Node

from verifier.cobol.syntax import Program
from verifier.langpacks import ts
from verifier.langpacks.base import (
    BuildResult,
    CallSite,
    CatchSite,
    FieldSym,
    LangPack,
    Literal_,
    MethodSym,
    NotApplicable,
    PackContext,
    ResolvedProgram,
    SymbolIndex,
    TypeSym,
)
from verifier.langpacks.java.pack import excerpt, rewrite_run_command
from verifier.manifest import ProgramMap, loose, pascal, snake
from verifier.report.schema import Finding
from verifier.sandbox.docker_runner import Mount

BUILD_DIR = ".verifier-build"
BIN_DIR = f"{BUILD_DIR}/bin"
DEFAULT_MODULE = "verifier.local/target"
GO_VERSION_DIRECTIVE = "1.22"
COBOLRT_GO = "/opt/cobolrt/go/cobolrt"
VET_MARK = "@@VERIFIER-VET@@"
GO_ENV = {
    "GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off", "GOWORK": "off",
    "CGO_ENABLED": "0", "GOCACHE": f"/tgt/{BUILD_DIR}/gocache", "GOPATH": f"/tgt/{BUILD_DIR}/gopath",
    "GOTELEMETRY": "off",
}
_SKIP_PARTS = {BUILD_DIR, "vendor", "testdata", ".git"}

_GO_DIAG = re.compile(
    r"^(?:vet: )?(?P<file>[^\s:#][^:\n]*\.go):(?P<line>\d+)(?::(?P<col>\d+))?: (?P<msg>.+)$", re.M
)


def _skipped(rel_path: str) -> bool:
    parts = rel_path.split("/")
    return any(p in _SKIP_PARTS or p.startswith((".", "_")) for p in parts[:-1]) or rel_path.endswith("_test.go")


def bin_name(pkg_dir: str) -> str:
    """Binary file name for a main package directory (repo-relative; "" = the root)."""
    return pkg_dir.replace("/", "__") if pkg_dir else "_root"


# ---------------------------------------------------------------------------------------------
# index model
# ---------------------------------------------------------------------------------------------
@dataclass
class GoPackage:
    dir: str  # repo-relative directory, "" = repository root
    name: str = ""  # package clause
    files: list[str] = field(default_factory=list)
    main_file: str | None = None  # file holding `func main` (package main only)
    funcs: list[MethodSym] = field(default_factory=list)
    vars: list[FieldSym] = field(default_factory=list)
    structs: list[TypeSym] = field(default_factory=list)

    @property
    def has_main(self) -> bool:
        return self.name == "main" and self.main_file is not None

    @property
    def base(self) -> str:
        return self.dir.rsplit("/", 1)[-1] if self.dir else ""


@dataclass
class GoSymbolIndex(SymbolIndex):
    packages: dict[str, GoPackage] = field(default_factory=dict)  # dir -> package
    module_dirs: list[str] = field(default_factory=list)  # dirs holding a go.mod ("" = root)


def module_path(go_mod: str) -> str | None:
    m = re.search(r"^\s*module\s+(\S+)", go_mod, re.M)
    return m.group(1).strip('"') if m else None


def parse_go_dependencies(content: str) -> list[str]:
    """Module paths required by a go.mod (other dependency files yield nothing)."""
    if not re.search(r"^\s*module\s+\S+", content, re.M):
        return []
    deps: list[str] = []
    in_block = False
    for raw in content.splitlines():
        ln = raw.split("//", 1)[0].strip()
        if in_block:
            if ln.startswith(")"):
                in_block = False
            elif ln:
                deps.append(ln.split()[0])
        elif ln.startswith("require"):
            rest = ln[len("require"):].strip()
            if rest.startswith("("):
                in_block = True
            elif rest:
                deps.append(rest.split()[0])
    return deps


# ---------------------------------------------------------------------------------------------
class GoPack(LangPack):
    name = "go"
    file_suffixes = (".go",)

    def sources(self, root: Path) -> list[str]:
        return [p.relative_to(root).as_posix() for p in sorted(root.rglob("*.go"))
                if not _skipped(p.relative_to(root).as_posix())]

    # ---- T0a ------------------------------------------------------------------------------
    def build(self, ctx: PackContext) -> BuildResult:
        tgt = ctx.target_root
        start = time.monotonic()
        idx = self.index(tgt)
        if not idx.packages:
            return BuildResult(False, "go build", "no Go sources found", 0.0, [
                Finding(check="T0a.build", severity="ERROR", message="no Go sources found in the target repo")])
        notes: list[Finding] = []
        mod_dirs = list(idx.module_dirs)
        if not mod_dirs:
            (tgt / "go.mod").write_text(f"module {DEFAULT_MODULE}\n\ngo {GO_VERSION_DIRECTIVE}\n", "utf-8")
            mod_dirs = [""]
            notes.append(Finding(check="T0a.build", severity="INFO",
                                 message=f"the target has no go.mod; the verifier created one in the workspace copy "
                                         f"only (module {DEFAULT_MODULE}, go {GO_VERSION_DIRECTIVE})"))
        notes.extend(self._link_cobolrt(ctx, tgt, mod_dirs, idx))
        (tgt / BIN_DIR).mkdir(parents=True, exist_ok=True)
        mains = sorted(d for d, p in idx.packages.items() if p.has_main)
        steps: list[str] = []
        shown: list[str] = []
        m = ctx.manifest
        if m is not None and m.build is not None:
            workdir = m.build.workdir.strip("/") or "."
            steps.append(f"cd /tgt/{shlex.quote(workdir)} && ( {m.build.command} ) || exit 1")
            shown.append(m.build.command)
        for md in mod_dirs:
            cd = f"/tgt/{md}" if md else "/tgt"
            steps.append(f"mkdir -p /tmp/verifier-gobuild && cd {shlex.quote(cd)} && go build -o /tmp/verifier-gobuild/ ./... || exit 1")
            shown.append(f"(cd {md or '.'} && go build ./...)")
        for d in mains:
            owner = _owning_module(d, mod_dirs)
            if owner is None:
                continue
            rel = d[len(owner):].lstrip("/") if owner else d
            cd = f"/tgt/{owner}" if owner else "/tgt"
            out = f"/tgt/{BIN_DIR}/{bin_name(d)}"
            steps.append(f"cd {shlex.quote(cd)} && go build -trimpath -o {shlex.quote(out)} "
                         f"./{shlex.quote(rel) if rel else '.'} || exit 1")
            shown.append(f"go build -o {BIN_DIR}/{bin_name(d)} ./{d or '.'}")
        steps.append(f"echo {VET_MARK}")
        for md in mod_dirs:
            cd = f"/tgt/{md}" if md else "/tgt"
            steps.append(f"cd {shlex.quote(cd)} && go vet ./...; echo \"@@VERIFIER-VET-EXIT $?@@\"")
            shown.append(f"(cd {md or '.'} && go vet ./...) [warnings]")
        script = "go version; " + "; ".join(steps) + "; exit 0"
        command = " && ".join(shown)
        mounts = [Mount(tgt, "/tgt", read_only=False)]
        if ctx.runtime_dir is not None:
            mounts.append(Mount(ctx.runtime_dir, "/opt/cobolrt", read_only=True))
        res = ctx.runner.run(["bash", "-c", script], mounts=mounts, env=dict(GO_ENV),
                             network=ctx.config.allow_build_network, timeout_s=ctx.config.limits.build_timeout_s)
        out = res.text()
        diags = parse_diagnostics(out, tgt, mod_dirs)
        ok = res.ok and not any(d.severity == "ERROR" for d in diags)
        if not res.ok and not any(d.severity == "ERROR" for d in diags):
            diags.insert(0, Finding(check="T0a.build", severity="ERROR",
                                    message=f"build command failed (exit {res.returncode}): {out.strip()[-1500:]}"))
        return BuildResult(ok, command, out, time.monotonic() - start, notes + diags, res.timed_out)

    def _link_cobolrt(self, ctx: PackContext, tgt: Path, mod_dirs: list[str], idx: GoSymbolIndex) -> list[Finding]:
        """If the code imports the runtime library's module, point go.mod at the mounted copy."""
        if ctx.runtime_dir is None:
            return []
        rt_mod_file = ctx.runtime_dir / "go" / "cobolrt" / "go.mod"
        if not rt_mod_file.exists():
            return []
        rt_mod = module_path(rt_mod_file.read_text("utf-8", errors="replace"))
        if not rt_mod or not any(i == rt_mod or i.startswith(rt_mod + "/") for i, _f, _l in idx.imports):
            return []
        out = []
        for md in mod_dirs:
            gm = tgt / md / "go.mod" if md else tgt / "go.mod"
            text = gm.read_text("utf-8", errors="replace") if gm.exists() else ""
            if re.search(rf"^\s*replace\s+{re.escape(rt_mod)}\b", text, re.M):
                continue
            add = ""
            if rt_mod not in parse_go_dependencies(text):
                add += f"\nrequire {rt_mod} v0.0.0\n"
            add += f"\nreplace {rt_mod} => {COBOLRT_GO}\n"
            gm.write_text(text + add, "utf-8")
            out.append(Finding(check="T0a.build", severity="INFO",
                               message=f"go.mod in the workspace copy ({md or '.'}) points {rt_mod} at the mounted "
                                       f"runtime library {COBOLRT_GO}"))
        return out

    # ---- index ---------------------------------------------------------------------------
    def index(self, root: Path) -> GoSymbolIndex:
        idx = GoSymbolIndex()
        parser = ts.parser_for("go")
        for p in sorted(root.rglob("go.mod")):
            r = p.relative_to(root).as_posix()
            if not _skipped(r):
                idx.module_dirs.append(r.rsplit("/", 1)[0] if "/" in r else "")
        for p in sorted(root.rglob("*.go")):
            r = p.relative_to(root).as_posix()
            if r.startswith(BUILD_DIR + "/"):
                continue
            data = p.read_bytes()
            idx.files[r] = data
            if _skipped(r):
                continue
            tree = parser.parse(data)
            if ts.has_error(tree.root_node):
                idx.parse_errors.append(f"{r}: tree-sitter reports syntax errors")
            d = r.rsplit("/", 1)[0] if "/" in r else ""
            pkg = idx.packages.setdefault(d, GoPackage(d))
            pkg.files.append(r)
            _index_go(tree.root_node, r, idx, pkg)
        for pkg in idx.packages.values():
            idx.types.append(_package_symbol(pkg, None))
        return idx

    # ---- resolution ----------------------------------------------------------------------
    def resolve_program(
        self, ctx: PackContext, index: SymbolIndex, prog: Program, entry: ProgramMap | None
    ) -> ResolvedProgram:
        notes: list[str] = []
        source = "manifest" if entry is not None else "convention"
        packages = index.packages if isinstance(index, GoSymbolIndex) else {}
        if isinstance(index, GoSymbolIndex) and not index.module_dirs:
            notes.append(f"the target has no go.mod; the verifier creates one in the workspace copy only "
                         f"(module {DEFAULT_MODULE})")
        pkg = _find_package(packages, prog.program_id, entry, notes)
        struct_pref = entry.class_.rsplit(".", 1)[-1] if entry is not None and entry.class_ else None
        type_sym = _package_symbol(pkg, struct_pref, notes) if pkg is not None else None
        run_cmd: str | None = None
        if entry is not None and entry.run is not None:
            run_cmd = rewrite_run_command(entry.run.command, ctx.target_root)
        elif pkg is not None:
            run_cmd = f"/tgt/{BIN_DIR}/{bin_name(pkg.dir)}"
        files: dict[str, str] = {}
        for sel in prog.selects:
            if sel.assign and sel.assign_kind in ("literal", "name"):
                files[sel.name] = sel.assign
        if entry is not None:
            for file_map in entry.files:
                files[file_map.cobol_select.upper()] = file_map.path
        methods = type_sym.methods if type_sym is not None else []
        explicit = {u.cobol_paragraph.upper(): u.target_symbol for u in entry.units} if entry else {}
        units: dict[str, str | None] = {}
        locs: dict[str, MethodSym | None] = {}
        for para in prog.paragraphs:
            want = (explicit.get(para.name) or pascal(para.name)).rsplit(".", 1)[-1]
            ms = next((x for x in methods if x.name == want), None) or next(
                (x for x in methods if loose(x.name) == loose(want)), None)
            units[para.name] = ms.name if ms else explicit.get(para.name)
            locs[para.name] = ms
        fields: dict[str, dict[str, Any]] = {}
        fsyms = type_sym.fields if type_sym is not None else []
        if entry is not None and entry.fields:
            for fm in entry.fields:
                tname = fm.target.rsplit(".", 1)[-1]
                f = next((x for x in fsyms if x.name == tname), None)
                fields[fm.cobol.upper()] = {
                    "target": fm.target, "declared": fm.declared.model_dump(exclude_none=True) if fm.declared else None,
                    "target_type": fm.target_type or (f.type_text if f else None) or None,
                    "location": (f.file, f.line) if f else None, "source": "manifest",
                }
        for item in prog.all_items():
            if item.is_filler or not item.is_elementary or item.name in fields:
                continue
            want = pascal(item.name)
            f = next((x for x in fsyms if x.name == want), None) or next(
                (x for x in fsyms if loose(x.name) == loose(item.name)), None)
            if f is not None:
                fields[item.name] = {"target": f.name, "declared": None, "target_type": f.type_text or None,
                                     "location": (f.file, f.line), "source": "convention"}
        if entry is not None and (not entry.fields or not entry.units):
            source = "mixed"
        return ResolvedProgram(prog.program_id, prog.source_file, type_sym, run_cmd, files, units, locs, fields,
                               source, notes)

    def run_command(self, ctx: PackContext, resolved: ResolvedProgram) -> list[str] | NotApplicable:
        if resolved.run_command is None:
            return NotApplicable(f"no Go main package found for program {resolved.program_id} "
                                 f"(convention: directory {snake(resolved.program_id)}/ with package main)")
        return ["sh", "-c", resolved.run_command + ' "$@"', "sh"]

    def static_rules(self) -> dict[str, Any]:
        return GO_RULES


# ---------------------------------------------------------------------------------------------
def _owning_module(pkg_dir: str, mod_dirs: list[str]) -> str | None:
    best: str | None = None
    for md in mod_dirs:
        inside = md == "" or pkg_dir == md or pkg_dir.startswith(md + "/")
        if inside and (best is None or len(md) > len(best)):
            best = md
    return best


def _find_package(packages: dict[str, GoPackage], program_id: str, entry: ProgramMap | None,
                  notes: list[str]) -> GoPackage | None:
    mains = [p for p in packages.values() if p.has_main]
    cands: list[GoPackage] = []
    if entry is not None and entry.package:
        want = entry.package.strip("/").removeprefix("./")
        cands = [p for p in mains if p.dir == want or (want and want.endswith("/" + p.dir) and p.dir)
                 or (want in (".", "") and p.dir == "")]
        if not cands:
            notes.append(f"manifest package {entry.package} not found (no `package main` with `func main` there)")
    if not cands:
        key = snake(program_id)
        cands = [p for p in mains if p.base == key] or [p for p in mains if p.base and loose(p.base) == loose(program_id)]
    if not cands and entry is not None and entry.class_:
        sname = entry.class_.rsplit(".", 1)[-1]
        cands = [p for p in mains if any(s.name == sname for s in p.structs)]
    if not cands:
        root = packages.get("")
        if root is not None and root.has_main and len(mains) == 1:
            cands = [root]
            notes.append(f"using the repository root main package for {program_id} (the only main package)")
    if not cands:
        return None
    cands.sort(key=lambda p: (p.dir.count("/"), p.dir))
    if len(cands) > 1:
        notes.append(f"several candidate packages for {program_id}: {[c.dir or '.' for c in cands]}; "
                     f"using {cands[0].dir or '.'}")
    return cands[0]


def _package_symbol(pkg: GoPackage, struct_pref: str | None, notes: list[str] | None = None) -> TypeSym:
    """One TypeSym per package: package funcs/vars plus every struct's methods/fields."""
    structs = list(pkg.structs)
    if struct_pref:
        pref = [s for s in structs if s.name == struct_pref]
        if not pref and notes is not None:
            notes.append(f"manifest struct {struct_pref} not found in package {pkg.dir or '.'}")
        structs = pref + [s for s in structs if s.name != struct_pref]
    methods: list[MethodSym] = []
    fields: list[FieldSym] = []
    for s in structs:
        methods.extend(s.methods)
        fields.extend(s.fields)
    methods.extend(pkg.funcs)
    fields.extend(pkg.vars)
    return TypeSym(pkg.name or pkg.base, pkg.dir or ".", pkg.main_file or (pkg.files[0] if pkg.files else ""), 1,
                   methods, fields, pkg.has_main)


# ---------------------------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------------------------
def parse_diagnostics(output: str, root: Path, mod_dirs: list[str] | None = None) -> list[Finding]:
    build_part, _, vet_part = output.partition(VET_MARK)
    diags: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    known = {p.relative_to(root).as_posix() for p in root.rglob("*.go")} if root.exists() else set()

    def locate(f: str) -> str:
        for prefix in ("/tgt/", "./"):
            if f.startswith(prefix):
                f = f[len(prefix):]
        if f in known:
            return f
        for md in mod_dirs or []:
            cand = f"{md}/{f}" if md else f
            if cand in known:
                return cand
        hits = [k for k in known if k.endswith("/" + f)]
        return hits[0] if len(hits) == 1 else f

    def scan(part: str, check: str, sev: Literal["ERROR", "WARNING"]) -> None:
        for m in _GO_DIAG.finditer(part):
            f = locate(m.group("file"))
            ln = int(m.group("line"))
            msg = m.group("msg").strip()
            key = (f, ln, msg)
            if key in seen:
                continue
            seen.add(key)
            col = m.group("col")
            diags.append(Finding(check=check, severity=sev, message=msg if check == "T0a.build" else f"go vet: {msg}",
                                 file=f, line=ln, column=int(col) if col else None, excerpt=excerpt(root / f, ln)))

    scan(build_part, "T0a.build", "ERROR")
    scan(vet_part, "T0a.vet", "WARNING")
    for em in re.finditer(r"@@VERIFIER-VET-EXIT (\d+)@@", vet_part):
        if em.group(1) != "0" and not any(d.check == "T0a.vet" for d in diags):
            diags.append(Finding(check="T0a.vet", severity="WARNING",
                                 message=f"go vet exited {em.group(1)}: {vet_part[: em.start()].strip()[-600:]}"))
    return diags


# ---------------------------------------------------------------------------------------------
# tree-sitter indexing
# ---------------------------------------------------------------------------------------------
_PANIC_OR_EXIT = {"panic", "os.Exit", "log.Fatal", "log.Fatalf", "log.Fatalln", "log.Panic", "log.Panicf"}


def _go_string(node: Node) -> str | None:
    raw = ts.text(node)
    if node.type == "raw_string_literal":
        return raw[1:-1]
    if node.type == "interpreted_string_literal":
        return ts.unescape(raw[1:-1])
    return None


def _number(raw: str) -> str | None:
    s = raw.replace("_", "")
    if s[:2].lower() in ("0o", "0b"):
        try:
            return str(int(s, 0))
        except ValueError:
            return None
    if len(s) > 1 and s[0] == "0" and s.isdigit():  # legacy octal
        return str(int(s, 8))
    return ts.normalise_number(s)


def _infer_go_type(value: Node | None) -> str:
    if value is None:
        return ""
    t = value.type
    if t == "int_literal":
        return "int"
    if t == "float_literal":
        return "float64"
    if t in ("interpreted_string_literal", "raw_string_literal"):
        return "string"
    if t == "rune_literal":
        return "rune"
    if t == "unary_expression":
        return _infer_go_type(value.child_by_field_name("operand"))
    if t == "composite_literal":
        return ts.text(value.child_by_field_name("type"))
    if t == "call_expression":
        fn = ts.text(value.child_by_field_name("function"))
        if fn in ("int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32", "uint64",
                  "float32", "float64", "string", "byte", "rune"):
            return fn
    return ""


class _FileIndexer:
    def __init__(self, file: str, idx: GoSymbolIndex, pkg: GoPackage) -> None:
        self.file, self.idx, self.pkg = file, idx, pkg
        self.aliases: dict[str, str] = {}

    def struct_for(self, name: str) -> TypeSym:
        s = next((x for x in self.pkg.structs if x.name == name), None)
        if s is None:
            q = f"{self.pkg.dir or self.pkg.name}.{name}"
            s = TypeSym(name, q, self.file, 0)
            self.pkg.structs.append(s)
            self.idx.types.append(s)
        return s

    def top_level(self, root: Node) -> None:
        for child in root.named_children:
            t = child.type
            if t == "package_clause":
                self.pkg.name = ts.text(child.named_children[0]) if child.named_children else ""
            elif t == "import_declaration":
                for spec in ts.walk(child):
                    if spec.type != "import_spec":
                        continue
                    path_node = spec.child_by_field_name("path")
                    path = _go_string(path_node) if path_node is not None else None
                    if path is None:
                        continue
                    name_node = spec.child_by_field_name("name")
                    alias = ts.text(name_node) if name_node is not None else path.rsplit("/", 1)[-1]
                    if re.fullmatch(r"v\d+", alias) and "/" in path:  # math/rand/v2 → rand
                        alias = path.rsplit("/", 2)[-2]
                    if alias not in ("_", "."):
                        self.aliases[alias] = path
                    self.idx.imports.append((path, self.file, ts.line(spec)))
            elif t == "function_declaration":
                name = ts.text(child.child_by_field_name("name"))
                self.pkg.funcs.append(self.method(child, name))
                if name == "main" and self.pkg.main_file is None:
                    self.pkg.main_file = self.file
            elif t == "method_declaration":
                recv = child.child_by_field_name("receiver")
                rtype = ""
                if recv is not None:
                    for c in ts.walk(recv):
                        if c.type == "type_identifier":
                            rtype = ts.text(c)
                            break
                ms = self.method(child, ts.text(child.child_by_field_name("name")))
                if rtype:
                    self.struct_for(rtype).methods.append(ms)
                else:
                    self.pkg.funcs.append(ms)
            elif t in ("var_declaration", "const_declaration"):
                if t == "const_declaration":
                    continue
                for spec in ts.walk(child):
                    if spec.type == "var_spec":
                        self.var_spec(spec)
            elif t == "type_declaration":
                for spec in child.named_children:
                    if spec.type != "type_spec":
                        continue
                    tnode = spec.child_by_field_name("type")
                    name = ts.text(spec.child_by_field_name("name"))
                    if tnode is None or tnode.type != "struct_type":
                        continue
                    s = self.struct_for(name)
                    s.file, s.line = self.file, ts.line(spec)
                    for fd in ts.walk(tnode):
                        if fd.type != "field_declaration":
                            continue
                        ftype = ts.text(fd.child_by_field_name("type"))
                        for nm in fd.children_by_field_name("name"):
                            s.fields.append(FieldSym(ts.text(nm), ftype, self.file, ts.line(nm)))

    def method(self, node: Node, name: str) -> MethodSym:
        params = node.child_by_field_name("parameters")
        plist = [ts.text(p) for p in params.named_children] if params is not None else []
        return MethodSym(name, self.file, ts.line(node), ts.end_line(node), plist, node.type == "function_declaration")

    def var_spec(self, spec: Node) -> None:
        tnode = spec.child_by_field_name("type")
        names = spec.children_by_field_name("name")
        value = spec.child_by_field_name("value")
        vals = list(value.named_children) if value is not None else []
        for i, nm in enumerate(names):
            val = vals[i] if i < len(vals) else None
            ttext = ts.text(tnode) if tnode is not None else _infer_go_type(val)
            self.pkg.vars.append(FieldSym(ts.text(nm), ttext, self.file, ts.line(nm),
                                          ts.text(val) if val is not None else None))

    def canonical(self, callee: str) -> str:
        head, sep, rest = callee.partition(".")
        path = self.aliases.get(head)
        return f"{path}.{rest}" if path is not None and sep else callee

    def uses(self, root: Node) -> None:
        idx, file = self.idx, self.file
        for n in ts.walk(root):
            t = n.type
            if t in ("int_literal", "float_literal"):
                raw = ts.text(n)
                val = _number(raw)
                if val is None:
                    continue
                par = n.parent
                if par is not None and par.type == "unary_expression" and ts.text(par).startswith("-"):
                    val = "0" if val == "0" else ("-" + val if not val.startswith("-") else val)
                idx.literals.append(Literal_("float" if t == "float_literal" else "int", raw, val, file, ts.line(n)))
                if t == "float_literal":
                    idx.float_uses.append((raw, file, ts.line(n)))
            elif t in ("interpreted_string_literal", "raw_string_literal"):
                par = n.parent
                if par is not None and par.type == "import_spec":
                    continue
                v = _go_string(n)
                if v is not None:
                    idx.literals.append(Literal_("str", ts.text(n), v, file, ts.line(n)))
            elif t == "call_expression":
                fn = n.child_by_field_name("function")
                if fn is None:
                    continue
                raw_callee = re.sub(r"\s+", "", ts.text(fn))
                callee = self.canonical(raw_callee)
                args = n.child_by_field_name("arguments")
                texts: list[str] = []
                strs: list[str] = []
                if args is not None:
                    named = list(args.named_children)
                    texts = [ts.text(a) for a in named]
                    if named:
                        sv = _go_string(named[0])
                        if sv is not None:
                            strs.append(sv)
                idx.calls.append(CallSite(callee, file, ts.line(n), texts, strs))
                if raw_callee in ("float32", "float64"):
                    idx.float_uses.append((raw_callee, file, ts.line(n)))
                if raw_callee == "recover":
                    idx.catches.append(CatchSite(["recover()"], file, ts.line(n), self.recover_swallows(n)))
            elif t == "type_identifier" and ts.text(n) in ("float32", "float64"):
                idx.float_uses.append((ts.text(n), file, ts.line(n)))

    def recover_swallows(self, call: Node) -> bool:
        """`recover()` swallows unless its function re-panics or exits."""
        cur = call.parent
        while cur is not None and cur.type not in ("func_literal", "function_declaration", "method_declaration"):
            cur = cur.parent
        if cur is None:
            return True
        body = cur.child_by_field_name("body")
        if body is None:
            return True
        for c in ts.walk(body):
            if c.type == "call_expression":
                callee = self.canonical(re.sub(r"\s+", "", ts.text(c.child_by_field_name("function"))))
                if callee in _PANIC_OR_EXIT:
                    return False
        return True


def _index_go(root: Node, file: str, idx: GoSymbolIndex, pkg: GoPackage) -> None:
    fi = _FileIndexer(file, idx, pkg)
    fi.top_level(root)
    fi.uses(root)


# ---------------------------------------------------------------------------------------------
# static rule tables (consumed by tiers/t0_static.py)
# ---------------------------------------------------------------------------------------------
def go_type_base(type_text: str) -> str:
    """Element/base type for the data-mapping check: `[4]int64` → `int64`, `*big.Int` → `Int`,
    byte/rune slices and arrays are text (`[]byte`)."""
    t = type_text.strip()
    for _ in range(4):
        t = t.lstrip("*").strip()
        m = re.fullmatch(r"\[\s*[\w.]*\s*\](.+)", t)
        if not m:
            break
        elem = m.group(1).strip()
        if elem in ("byte", "rune", "uint8"):
            return "[]byte"
        t = elem
    return t.split(".")[-1]


GO_STDLIB_ALLOWED = [
    "bufio", "bytes", "cmp", "container", "encoding/binary", "encoding/hex", "errors", "fmt", "io", "math",
    "os", "path", "path/filepath", "slices", "maps", "sort", "strconv", "strings", "time", "unicode",
    "unicode/utf8", "unicode/utf16", "cobolrt",
]

GO_RULES: dict[str, Any] = {
    "forbidden_calls": [
        (r"^time\.(Now|Since|Until)$", "clock", "reads the wall clock (use the injected clock COBOL_VERIFIER_FAKE_TIME)"),
        (r"^math/rand(/v2)?\.", "rng", "uses an uninjected random source"),
        (r"^crypto/rand\.", "rng", "uses an uninjected random source"),
        (r"^os/exec\.", "process", "executes a process"),
        (r"^os\.(StartProcess|FindProcess)$", "process", "executes a process"),
        (r"^syscall\.", "process", "uses raw system calls"),
        (r"^reflect\.", "reflection", "uses reflection"),
        (r"^unsafe\.", "reflection", "uses unsafe"),
        (r"^net(/[\w/]+)?\.", "network", "network access"),
        (r"^plugin\.", "process", "loads plugins"),
    ],
    "warning_calls": [
        (r"^os\.(Getenv|LookupEnv|Environ)$", "env", "reads environment variables"),
    ],
    "forbidden_new": [],
    "forbidden_imports": [
        (r"^net(/|$)", "network", "network access"),
        (r"^os/exec$", "process", "executes a process"),
        (r"^(syscall|golang\.org/x/sys(/.*)?)$", "process", "uses raw system calls"),
        (r"^(reflect|unsafe)$", "reflection", "uses reflection / unsafe"),
        (r"^(plugin|C|runtime/cgo)$", "process", "loads native code"),
        (r"^(math/rand(/v2)?|crypto/rand)$", "rng", "imports an uninjected random source"),
    ],
    "file_open_calls": [
        r"^os\.(Open|OpenFile|Create|ReadFile|WriteFile|Remove|RemoveAll|Rename|Mkdir|MkdirAll|ReadDir|Stat|Lstat|"
        r"Truncate|Chmod|Chdir)$",
        r"^io/ioutil\.(ReadFile|WriteFile|ReadDir)$",
    ],
    "allowed_import_prefixes": GO_STDLIB_ALLOWED,
    "import_separator": "/",
    "parse_dependencies": parse_go_dependencies,
    "allowed_dependencies": ["cobolrt"],
    "decimal_types_ok": ["Decimal", "CobolDecimal", "Rat"],
    "integer_types": {"int8": 2, "uint8": 2, "byte": 2, "int16": 4, "uint16": 4, "int32": 9, "uint32": 9,
                      "rune": 9, "int64": 18, "int": 18, "uint64": 19, "uint": 19, "Int": 10**6},
    "float_types": ["float32", "float64", "complex64", "complex128", "Float"],
    "string_types": ["string", "[]byte", "Builder", "PicX"],
    "type_base": go_type_base,
}
