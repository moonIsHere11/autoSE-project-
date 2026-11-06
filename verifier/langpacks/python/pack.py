"""Python language pack: build (py_compile + mypy), tree-sitter index, resolution, run command.

Conventions (docs/INTERFACE.md section 2): program → module `snake_case(PROGRAM-ID).py` anywhere in
the repo (or a package `snake_case(PROGRAM-ID)/__main__.py`), run as `python3 -m <dotted module>`
with cwd = the per-case directory; paragraph → function or method `snake_case`; field → module
variable or attribute `snake_case` (class attribute, dataclass field or `self.x = …`).
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
from verifier.manifest import ProgramMap, loose, snake
from verifier.report.schema import Finding
from verifier.sandbox.docker_runner import Mount

BUILD_DIR = ".verifier-build"
COBOLRT_PY = "/opt/cobolrt/python"
MYPY_MARK = "@@VERIFIER-MYPY@@"
_SKIP_PARTS = {BUILD_DIR, "__pycache__", ".venv", "venv", "site-packages", ".git", ".mypy_cache", ".tox",
               "node_modules", ".pytest_cache"}
_TEST_DIRS = {"test", "tests", "testing"}

# py_compile every module (no target code is executed); `-I` keeps the target's modules off sys.path
_PYCHECK = r"""
import py_compile, sys
bad = 0
for i, f in enumerate(open(sys.argv[1], encoding="utf-8").read().splitlines()):
    if not f:
        continue
    try:
        py_compile.compile(f, cfile="/tmp/verifier-pyc/%d.pyc" % i, doraise=True)
    except py_compile.PyCompileError as e:
        bad += 1
        ev = e.exc_value
        ln = getattr(ev, "lineno", None) or 0
        msg = getattr(ev, "msg", None) or str(ev)
        print("%s:%s: error: %s: %s" % (f, ln, type(ev).__name__, msg))
print("py_compile: %d module(s), %d with errors" % (len([x for x in open(sys.argv[1]).read().splitlines() if x]), bad))
sys.exit(1 if bad else 0)
"""

_COMPILE_DIAG = re.compile(r"^(?P<file>[^\s:][^:\n]*\.py):(?P<line>\d+): error: (?P<msg>.*)$", re.M)
_MYPY_DIAG = re.compile(
    r"^(?P<file>[^\s:][^:\n]*\.py):(?P<line>\d+)(?::(?P<col>\d+))?: (?P<sev>error|warning): (?P<msg>.*)$", re.M
)


def is_test_path(rel_path: str) -> bool:
    parts = rel_path.split("/")
    name = parts[-1]
    return (any(p in _TEST_DIRS for p in parts[:-1]) or name.startswith("test_") or name.endswith("_test.py")
            or name == "conftest.py")


def _skipped(rel_path: str) -> bool:
    return any(p in _SKIP_PARTS for p in rel_path.split("/"))


# ---------------------------------------------------------------------------------------------
# index model
# ---------------------------------------------------------------------------------------------
@dataclass
class PyModule:
    dotted: str  # importable dotted name (relative to `import_root`)
    file: str  # repo-relative path
    import_root: str  # repo-relative directory that must be on sys.path ("" = repo root)
    has_main_guard: bool = False
    functions: list[MethodSym] = field(default_factory=list)
    variables: list[FieldSym] = field(default_factory=list)
    classes: list[TypeSym] = field(default_factory=list)

    @property
    def stem(self) -> str:
        return self.file.rsplit("/", 1)[-1][:-3]


@dataclass
class PySymbolIndex(SymbolIndex):
    modules: dict[str, PyModule] = field(default_factory=dict)  # file -> module


def module_name(root: Path, rel_path: str) -> tuple[str, str]:
    """(dotted module, import root) of a repo-relative .py file: climb while `__init__.py` exists."""
    parts = rel_path[:-3].split("/")
    d = len(parts) - 1  # index of the first directory that is NOT a package
    while d > 0 and (root.joinpath(*parts[:d]) / "__init__.py").exists():
        d -= 1
    mod_parts = parts[d:]
    if mod_parts[-1] in ("__init__", "__main__") and len(mod_parts) > 1:
        mod_parts = mod_parts[:-1]
    return ".".join(mod_parts), "/".join(parts[:d])


# ---------------------------------------------------------------------------------------------
class PythonPack(LangPack):
    name = "python"
    file_suffixes = (".py",)

    def sources(self, root: Path) -> list[str]:
        out = []
        for p in sorted(root.rglob("*.py")):
            r = p.relative_to(root).as_posix()
            if _skipped(r) or is_test_path(r):
                continue
            out.append(r)
        return out

    # ---- T0a ------------------------------------------------------------------------------
    def build(self, ctx: PackContext) -> BuildResult:
        tgt = ctx.target_root
        m = ctx.manifest
        start = time.monotonic()
        srcs = self.sources(tgt)
        (tgt / BUILD_DIR).mkdir(parents=True, exist_ok=True)
        (tgt / BUILD_DIR / "sources.txt").write_text("".join(s + "\n" for s in srcs), "utf-8")
        if m is not None and m.build is not None:
            workdir = m.build.workdir.strip("/") or "."
            command = m.build.command
            script = f"cd /tgt/{shlex.quote(workdir)} && {command}"
        else:
            if not srcs:
                return BuildResult(False, "py_compile", "no Python sources found", 0.0, [
                    Finding(check="T0a.build", severity="ERROR", message="no Python modules found in the target repo")
                ])
            command = (f"python3 -I -B -c <py_compile each module in {BUILD_DIR}/sources.txt>; "
                       f"MYPYPATH={COBOLRT_PY} mypy --config-file /dev/null --cache-dir /dev/null "
                       "--ignore-missing-imports --no-error-summary --show-column-numbers <modules> (warnings only)")
            script = (
                "cd /tgt && mkdir -p /tmp/verifier-pyc && "
                f"python3 -I -B -c {shlex.quote(_PYCHECK)} {BUILD_DIR}/sources.txt; rc=$?; "
                f"echo {MYPY_MARK}; "
                'if [ "$rc" -eq 0 ]; then mypy --version; '
                f"MYPYPATH={COBOLRT_PY} xargs -d '\\n' -a {BUILD_DIR}/sources.txt mypy --config-file /dev/null "
                "--cache-dir /dev/null --ignore-missing-imports --no-error-summary --show-column-numbers "
                "--no-color-output; echo \"@@VERIFIER-MYPY-EXIT $?@@\"; fi; exit $rc"
            )
        mounts = [Mount(tgt, "/tgt", read_only=False)]
        if ctx.runtime_dir is not None:
            mounts.append(Mount(ctx.runtime_dir, "/opt/cobolrt", read_only=True))
        res = ctx.runner.run(["bash", "-c", script], mounts=mounts, network=ctx.config.allow_build_network,
                             timeout_s=ctx.config.limits.build_timeout_s,
                             env={"PYTHONDONTWRITEBYTECODE": "1"})
        out = res.text()
        diags = parse_diagnostics(out, tgt)
        ok = res.ok and not any(d.severity == "ERROR" for d in diags)
        if not res.ok and not any(d.severity == "ERROR" for d in diags):
            diags.insert(0, Finding(check="T0a.build", severity="ERROR",
                                    message=f"build command failed (exit {res.returncode}): {out.strip()[-1500:]}"))
        return BuildResult(ok, command, out, time.monotonic() - start, diags, res.timed_out)

    # ---- index ---------------------------------------------------------------------------
    def index(self, root: Path) -> PySymbolIndex:
        idx = PySymbolIndex()
        parser = ts.parser_for("python")
        for p in sorted(root.rglob("*.py")):
            r = p.relative_to(root).as_posix()
            if _skipped(r):
                continue
            data = p.read_bytes()
            idx.files[r] = data
            tree = parser.parse(data)
            if ts.has_error(tree.root_node):
                idx.parse_errors.append(f"{r}: tree-sitter reports syntax errors")
            if is_test_path(r):
                continue
            dotted, import_root = module_name(root, r)
            mod = PyModule(dotted, r, import_root)
            idx.modules[r] = mod
            _index_python(tree.root_node, r, idx, mod)
        return idx

    # ---- resolution ----------------------------------------------------------------------
    def resolve_program(
        self, ctx: PackContext, index: SymbolIndex, prog: Program, entry: ProgramMap | None
    ) -> ResolvedProgram:
        notes: list[str] = []
        source = "manifest" if entry is not None else "convention"
        modules = index.modules if isinstance(index, PySymbolIndex) else {}
        mod = _find_module(modules, prog.program_id, entry, notes)
        cls_pref: str | None = None
        if entry is not None and entry.class_:
            cls_pref = entry.class_.rsplit(".", 1)[-1]
        type_sym: TypeSym | None = None
        if mod is not None:
            type_sym = _program_symbol(mod, cls_pref, notes)
        run_cmd: str | None = None
        if entry is not None and entry.run is not None:
            run_cmd = rewrite_run_command(entry.run.command, ctx.target_root)
        elif mod is not None:
            run_cmd = python_run_command(mod)
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
            want = (explicit.get(para.name) or snake(para.name)).rsplit(".", 1)[-1]
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
            want = snake(item.name)
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
            return NotApplicable(f"no Python module found for program {resolved.program_id} "
                                 f"(convention: module {snake(resolved.program_id)}.py run as python3 -m)")
        return ["sh", "-c", resolved.run_command + ' "$@"', "sh"]

    def static_rules(self) -> dict[str, Any]:
        return PYTHON_RULES


# ---------------------------------------------------------------------------------------------
def python_run_command(mod: PyModule) -> str:
    paths = [f"/tgt/{mod.import_root}" if mod.import_root else "/tgt"]
    if "/tgt" not in paths:
        paths.append("/tgt")
    paths.append(COBOLRT_PY)
    # -B: never write bytecode (the repo is mounted read-only); -P: do not put the case directory
    # (cwd) on sys.path, so data files can never shadow modules
    return f"PYTHONPATH={':'.join(paths)} python3 -B -P -m {mod.dotted}"


def _find_module(modules: dict[str, PyModule], program_id: str, entry: ProgramMap | None,
                 notes: list[str]) -> PyModule | None:
    cands: list[PyModule] = []
    if entry is not None and (entry.module or entry.class_):
        if entry.module:
            want = entry.module.removesuffix(".py").replace("/", ".")
            cands = [m for m in modules.values() if m.dotted == want or m.file.removesuffix(".py").replace("/", ".")
                     == want or m.dotted.endswith("." + want)]
        if not cands and entry.class_ and "." in entry.class_:
            want = entry.class_.rsplit(".", 1)[0]
            cands = [m for m in modules.values() if m.dotted == want or m.dotted.endswith("." + want)]
        if not cands and entry.class_:
            cname = entry.class_.rsplit(".", 1)[-1]
            cands = [m for m in modules.values() if any(c.name == cname for c in m.classes)]
        if not cands:
            notes.append(f"manifest module/class {entry.module or entry.class_} not found in the target code")
    if not cands:
        key = snake(program_id)
        exact = [m for m in modules.values() if m.stem == key
                 or (m.stem == "__main__" and m.file.rsplit("/", 2)[-2:-1] == [key])]
        cands = exact or [m for m in modules.values() if loose(m.stem) == loose(program_id)]
    if not cands:
        return None
    cands = sorted(cands, key=lambda m: (not m.has_main_guard, m.file.count("/"), m.file))
    if len(cands) > 1:
        notes.append(f"several candidate modules for {program_id}: {[c.file for c in cands]}; using {cands[0].file}")
    return cands[0]


def _program_symbol(mod: PyModule, cls_pref: str | None, notes: list[str]) -> TypeSym:
    """One TypeSym for the program: module functions/variables plus the module's classes' members."""
    classes = list(mod.classes)
    if cls_pref:
        pref = [c for c in classes if c.name == cls_pref]
        if not pref:
            notes.append(f"manifest class {cls_pref} not found in {mod.file}")
        classes = pref + [c for c in classes if c.name != cls_pref]
    methods: list[MethodSym] = []
    fields: list[FieldSym] = []
    for c in classes:
        methods.extend(c.methods)
        fields.extend(c.fields)
    methods.extend(mod.functions)
    fields.extend(mod.variables)
    return TypeSym(mod.stem, mod.dotted, mod.file, 1, methods, fields, mod.has_main_guard)


# ---------------------------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------------------------
def parse_diagnostics(output: str, root: Path) -> list[Finding]:
    build_part, _, mypy_part = output.partition(MYPY_MARK)
    diags: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()

    def add(check: str, sev: Literal["ERROR", "WARNING", "INFO"], f: str, ln: int, msg: str,
            col: int | None = None) -> None:
        for prefix in ("/tgt/", "./"):
            if f.startswith(prefix):
                f = f[len(prefix):]
        key = (f, ln, msg)
        if key in seen:
            return
        seen.add(key)
        diags.append(Finding(check=check, severity=sev, message=msg.strip(), file=f, line=ln or None, column=col,
                             excerpt=excerpt(root / f, ln) if ln else None))

    for m in _COMPILE_DIAG.finditer(build_part):
        add("T0a.build", "ERROR", m.group("file"), int(m.group("line")), m.group("msg"))
    for m in _MYPY_DIAG.finditer(mypy_part):
        col = m.group("col")
        add("T0a.mypy", "WARNING", m.group("file"), int(m.group("line")), f"mypy: {m.group('msg')}",
            int(col) if col else None)
    exit_m = re.search(r"@@VERIFIER-MYPY-EXIT (\d+)@@", mypy_part)
    if exit_m and exit_m.group(1) not in ("0", "1"):
        tail = mypy_part[: exit_m.start()].strip()[-600:]
        diags.append(Finding(check="T0a.mypy", severity="WARNING",
                             message=f"mypy could not check the package (exit {exit_m.group(1)}): {tail}"))
    return diags


# ---------------------------------------------------------------------------------------------
# tree-sitter indexing
# ---------------------------------------------------------------------------------------------
_CATCH_ALL = {"Exception", "BaseException", "builtins.Exception", "builtins.BaseException"}
_EXIT_CALLS = {"sys.exit", "exit", "quit", "os._exit", "os.abort", "SystemExit"}
_FUNC_TYPES = ("function_definition",)


def _string_value(node: Node) -> str | None:
    """Value of a (non-f) string literal; None for f-strings with interpolations."""
    if node.type == "concatenated_string":
        parts = [_string_value(c) for c in node.named_children]
        return None if any(p is None for p in parts) else "".join(p or "" for p in parts)
    if node.type != "string":
        return None
    start = node.child(0)
    prefix = ts.text(start).lower() if start is not None else ""
    out: list[str] = []
    for c in node.named_children:
        if c.type == "interpolation":
            return None
        if c.type == "string_content":
            raw = ts.text(c)
            out.append(raw if "r" in prefix else ts.unescape(raw))
    return "".join(out)


def _is_docstring(node: Node) -> bool:
    par = node.parent
    return par is not None and par.type == "expression_statement" and par.named_child_count == 1


def _infer_type(value: Node | None) -> str:
    if value is None:
        return ""
    t = value.type
    if t == "integer":
        return "int"
    if t == "float":
        return "float"
    if t in ("string", "concatenated_string"):
        return "bytes" if ts.text(value).lower().startswith(("b", "rb", "br")) else "str"
    if t in ("true", "false"):
        return "bool"
    if t == "unary_operator":
        return _infer_type(value.child_by_field_name("argument"))
    if t == "parenthesized_expression" and value.named_child_count == 1:
        return _infer_type(value.named_children[0])
    if t == "binary_operator":
        left, right = value.child_by_field_name("left"), value.child_by_field_name("right")
        lt, rt = _infer_type(left), _infer_type(right)
        op = ts.text(value.child_by_field_name("operator"))
        if left is not None and left.type == "list" and op == "*":
            return lt
        if "float" in (lt, rt) or op == "/":
            return "float" if lt in ("int", "float") and rt in ("int", "float") else (lt or rt)
        return lt or rt
    if t == "list":
        el = [_infer_type(c) for c in value.named_children]
        known = [e for e in el if e]
        return f"list[{known[0]}]" if known else "list"
    if t == "call":
        fn = ts.text(value.child_by_field_name("function"))
        base = fn.rsplit(".", 1)[-1]
        if base in ("int", "float", "str", "bytes", "bytearray", "bool", "list", "dict", "Decimal", "Fraction"):
            return base
        if base[:1].isupper():
            return base
    return ""


def _annotation(node: Node | None) -> str:
    if node is None:
        return ""
    txt = ts.text(node).strip()
    if len(txt) >= 2 and txt[0] == txt[-1] and txt[0] in "'\"":
        txt = txt[1:-1]
    return txt


class _FileIndexer:
    def __init__(self, file: str, idx: PySymbolIndex, mod: PyModule) -> None:
        self.file, self.idx, self.mod = file, idx, mod
        self.aliases: dict[str, str] = {}

    # ---- imports / aliases ---------------------------------------------------------------
    def imports(self, root: Node) -> None:
        for n in ts.walk(root):
            if n.type == "import_statement":
                for name in n.children_by_field_name("name"):
                    if name.type == "aliased_import":
                        full = ts.text(name.child_by_field_name("name"))
                        self.aliases[ts.text(name.child_by_field_name("alias"))] = full
                    else:
                        full = ts.text(name)
                        head = full.split(".")[0]
                        self.aliases.setdefault(head, head)
                    self.idx.imports.append((full, self.file, ts.line(n)))
            elif n.type == "import_from_statement":
                modn = n.child_by_field_name("module_name")
                if modn is None:
                    continue
                relative = modn.type == "relative_import"
                module = ts.text(modn)
                if not relative:
                    self.idx.imports.append((module, self.file, ts.line(n)))
                for name in n.children_by_field_name("name"):
                    if name.type == "aliased_import":
                        nm = ts.text(name.child_by_field_name("name"))
                        alias = ts.text(name.child_by_field_name("alias"))
                    else:
                        nm = alias = ts.text(name)
                    self.aliases[alias] = f"{module}.{nm}" if not relative else f"{module}{nm}"

    def canonical(self, callee: str) -> str:
        head, sep, rest = callee.partition(".")
        full = self.aliases.get(head)
        if full is None or full == head:
            return callee
        return full + (sep + rest if sep else "")

    # ---- definitions ---------------------------------------------------------------------
    def module_level(self, root: Node) -> None:
        for child in root.named_children:
            node = child.child_by_field_name("definition") if child.type == "decorated_definition" else child
            if node is None:
                continue
            if node.type == "function_definition":
                self.mod.functions.append(self.method(node, child))
            elif node.type == "class_definition":
                self.klass(node, self.mod.dotted)
            elif node.type == "expression_statement":
                for a in node.named_children:
                    if a.type == "assignment":
                        self.assignment(a, self.mod.variables, attr_of=None)
            elif node.type == "if_statement":
                cond = ts.text(node.child_by_field_name("condition")).replace("'", '"').replace(" ", "")
                if cond in ('__name__=="__main__"', '"__main__"==__name__'):
                    self.mod.has_main_guard = True

    def method(self, node: Node, outer: Node) -> MethodSym:
        params = node.child_by_field_name("parameters")
        plist = [ts.text(p) for p in params.named_children] if params is not None else []
        decos = ts.text(outer) if outer.type == "decorated_definition" else ""
        return MethodSym(ts.text(node.child_by_field_name("name")), self.file, ts.line(outer), ts.end_line(node),
                         plist, "@staticmethod" in decos or "@classmethod" in decos)

    def klass(self, node: Node, outer: str) -> None:
        name = ts.text(node.child_by_field_name("name"))
        tsym = TypeSym(name, f"{outer}.{name}", self.file, ts.line(node))
        body = node.child_by_field_name("body")
        funcs: list[Node] = []
        if body is not None:
            for child in body.named_children:
                inner = child.child_by_field_name("definition") if child.type == "decorated_definition" else child
                if inner is None:
                    continue
                if inner.type == "function_definition":
                    tsym.methods.append(self.method(inner, child))
                    funcs.append(inner)
                    if ts.text(inner.child_by_field_name("name")) == "main":
                        tsym.has_main = True
                elif inner.type == "class_definition":
                    self.klass(inner, tsym.qualified)
                elif inner.type == "expression_statement":
                    for a in inner.named_children:
                        if a.type == "assignment":
                            self.assignment(a, tsym.fields, attr_of=None)
        # instance attributes: `self.x = …` (constructor first, so its initialiser gives the type)
        funcs.sort(key=lambda f: ts.text(f.child_by_field_name("name")) != "__init__")
        for f in funcs:
            params = f.child_by_field_name("parameters")
            first = params.named_children[0] if params is not None and params.named_children else None
            selfname = ts.text(first) if first is not None and first.type == "identifier" else "self"
            fbody = f.child_by_field_name("body")
            if fbody is None:
                continue
            for n in ts.walk(fbody):
                if n.type == "assignment":
                    self.assignment(n, tsym.fields, attr_of=selfname)
                elif n.type == "augmented_assignment":
                    pass
        self.mod.classes.append(tsym)
        self.idx.types.append(tsym)

    def assignment(self, a: Node, out: list[FieldSym], attr_of: str | None) -> None:
        left = a.child_by_field_name("left")
        if left is None:
            return
        typ = _annotation(a.child_by_field_name("type"))
        right = a.child_by_field_name("right")
        targets: list[tuple[Node, Node | None]] = []
        if left.type in ("pattern_list", "tuple_pattern"):
            vals = list(right.named_children) if right is not None and right.type in ("expression_list", "tuple") else []
            for i, t in enumerate(left.named_children):
                targets.append((t, vals[i] if i < len(vals) else None))
        else:
            targets.append((left, right))
        for tnode, val in targets:
            if attr_of is None:
                if tnode.type != "identifier":
                    continue
                name = ts.text(tnode)
            else:
                if tnode.type != "attribute" or ts.text(tnode.child_by_field_name("object")) != attr_of:
                    continue
                name = ts.text(tnode.child_by_field_name("attribute"))
            ttext = typ or _infer_type(val)
            existing = next((f for f in out if f.name == name), None)
            if existing is not None:
                if not existing.type_text and ttext:
                    existing.type_text = ttext
                continue
            out.append(FieldSym(name, ttext, self.file, ts.line(tnode), ts.text(val) if val is not None else None))

    # ---- uses ----------------------------------------------------------------------------
    def uses(self, root: Node) -> None:
        idx, file = self.idx, self.file
        for n in ts.walk(root):
            t = n.type
            if t in ("integer", "float"):
                raw = ts.text(n)
                if raw[-1:] in ("j", "J"):
                    continue
                val = _number(raw)
                if val is None:
                    continue
                par = n.parent
                if par is not None and par.type == "unary_operator" and ts.text(par).startswith("-"):
                    val = "0" if val == "0" else ("-" + val if not val.startswith("-") else val)
                idx.literals.append(Literal_("float" if t == "float" else "int", raw, val, file, ts.line(n)))
                if t == "float":
                    idx.float_uses.append((raw, file, ts.line(n)))
            elif t == "string":
                if _is_docstring(n) or (n.parent is not None and n.parent.type == "concatenated_string"):
                    continue
                v = _string_value(n)
                if v is None:
                    # f-string: literal parts still count for integrity / anti-overfitting
                    v = "".join(ts.text(c) for c in n.named_children if c.type == "string_content")
                idx.literals.append(Literal_("str", ts.text(n), v, file, ts.line(n)))
            elif t == "concatenated_string":
                if _is_docstring(n):
                    continue
                v = _string_value(n)
                if v is not None:
                    idx.literals.append(Literal_("str", ts.text(n), v, file, ts.line(n)))
            elif t == "call":
                fn = n.child_by_field_name("function")
                if fn is None:
                    continue
                callee = self.canonical(re.sub(r"\s+", "", ts.text(fn)))
                args = n.child_by_field_name("arguments")
                texts: list[str] = []
                strs: list[str] = []
                if args is not None:
                    positional = 0
                    for a in args.named_children:
                        texts.append(ts.text(a))
                        if a.type == "keyword_argument":
                            if ts.text(a.child_by_field_name("name")) == "file":
                                kv = a.child_by_field_name("value")
                                sv = _string_value(kv) if kv is not None else None
                                if sv is not None:
                                    strs.append(sv)
                            continue
                        if a.type in ("list_splat", "dictionary_splat"):
                            continue
                        positional += 1
                        if positional == 1:  # the path argument of open()/Path()/os.remove()...
                            sv = _string_value(a)
                            if sv is not None:
                                strs.append(sv)
                idx.calls.append(CallSite(callee, file, ts.line(n), texts, strs))
                if callee == "float":
                    idx.float_uses.append(("float", file, ts.line(n)))
            elif t == "type":
                if re.search(r"\bfloat\b", ts.text(n)):
                    idx.float_uses.append((ts.text(n), file, ts.line(n)))
            elif t in ("except_clause", "except_group_clause"):
                idx.catches.append(self.catch(n))

    def catch(self, n: Node) -> CatchSite:
        value = n.child_by_field_name("value")
        if value is None:
            value = next((c for c in n.named_children if c.type != "block"), None)
        types: list[str] = []
        if value is not None:
            tnode = value.named_children[0] if value.type == "as_pattern" and value.named_children else value
            if tnode.type in ("tuple", "parenthesized_expression"):
                types = [ts.text(c) for c in tnode.named_children]
            else:
                types = [ts.text(tnode)]
        label = types or ["bare except"]
        catch_all = not types or any(self.canonical(x) in _CATCH_ALL or x in _CATCH_ALL for x in types)
        swallows = False
        if catch_all:
            body = next((c for c in n.named_children if c.type == "block"), None)
            raises = exits = False
            if body is not None:
                for c in ts.walk(body):
                    if c.type == "raise_statement":
                        raises = True
                    elif c.type == "call":
                        callee = self.canonical(re.sub(r"\s+", "", ts.text(c.child_by_field_name("function"))))
                        if callee in _EXIT_CALLS:
                            exits = True
            swallows = not (raises or exits)
        return CatchSite(label, self.file, ts.line(n), swallows)


def _number(raw: str) -> str | None:
    s = raw.replace("_", "")
    if s[:2].lower() in ("0o", "0b"):
        try:
            return str(int(s, 0))
        except ValueError:
            return None
    return ts.normalise_number(s)


def _index_python(root: Node, file: str, idx: PySymbolIndex, mod: PyModule) -> None:
    fi = _FileIndexer(file, idx, mod)
    fi.imports(root)
    fi.module_level(root)
    fi.uses(root)
    idx.types.append(TypeSym(mod.stem, mod.dotted, file, 1, list(mod.functions), list(mod.variables),
                             mod.has_main_guard))


# ---------------------------------------------------------------------------------------------
# static rule tables (consumed by tiers/t0_static.py)
# ---------------------------------------------------------------------------------------------
_WRAPPERS = re.compile(r"^(?:typing\.)?(?:Optional|Final|ClassVar|Annotated|Required|NotRequired)\[(.*)\]$")
_CONTAINERS = re.compile(
    r"^(?:typing\.|collections\.abc\.)?(?:list|List|Sequence|MutableSequence|tuple|Tuple|deque|array)\[([^,\]]+)"
    r"(?:,\s*\.\.\.)?\]$")


def py_type_base(type_text: str) -> str:
    """Base type of a Python annotation for the data-mapping check (`Optional[list[float]]` → `float`)."""
    t = type_text.strip().strip("'\"")
    for _ in range(4):
        t = re.sub(r"\s*\|\s*None$|^None\s*\|\s*", "", t)
        m = _WRAPPERS.match(t)
        if m:
            t = m.group(1).split(",")[0].strip()
            continue
        m = _CONTAINERS.match(t)
        if m:
            t = m.group(1).strip()
            continue
        break
    return t.split(".")[-1]


def parse_python_dependencies(content: str) -> list[str]:
    """Distribution names from requirements.txt or pyproject.toml ([project] dependencies)."""
    if "[project]" in content or "[tool." in content or "[build-system]" in content:
        m = re.search(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]", content)
        items = re.findall(r"[\"']([^\"']+)[\"']", m.group(1)) if m else []
    else:
        items = [ln.split("#", 1)[0].strip() for ln in content.splitlines()]
        items = [i for i in items if i and not i.startswith("-")]
    return [re.split(r"[\s<>=!~;\[]", i, maxsplit=1)[0] for i in items if i]


PY_STDLIB_ALLOWED = [
    "__future__", "abc", "array", "binascii", "bisect", "builtins", "calendar", "cmath", "codecs", "collections",
    "contextlib", "copy", "dataclasses", "datetime", "decimal", "enum", "fractions", "functools", "heapq", "io",
    "itertools", "math", "numbers", "operator", "os", "pathlib", "random", "re", "string", "struct", "sys",
    "textwrap", "time", "typing", "unicodedata", "warnings", "zoneinfo", "cobolrt",
]

PYTHON_RULES: dict[str, Any] = {
    "forbidden_calls": [
        (r"^time\.(time|time_ns|localtime|gmtime|ctime|asctime|strftime)$", "clock",
         "reads the wall clock (use the injected clock COBOL_VERIFIER_FAKE_TIME)"),
        (r"^datetime\.(datetime\.|date\.)?(now|utcnow|today)$", "clock",
         "reads the wall clock (use the injected clock COBOL_VERIFIER_FAKE_TIME)"),
        (r"^random\.", "rng", "uses an uninjected random source"),
        (r"^secrets\.", "rng", "uses an uninjected random source"),
        (r"^os\.urandom$", "rng", "uses an uninjected random source"),
        (r"^uuid\.uuid[14]$", "rng", "uses an uninjected random source"),
        (r"^subprocess\.", "process", "executes a process"),
        (r"^os\.(system|popen|exec[lv]p?e?|spawn\w*|fork|forkpty|posix_spawnp?|kill|killpg)$", "process",
         "executes a process"),
        (r"^(builtins\.)?(eval|exec|compile|__import__|breakpoint)$", "process", "dynamic code execution"),
        (r"^importlib\.", "reflection", "uses reflection / dynamic import"),
        (r"^ctypes\.", "reflection", "uses ctypes"),
        (r"^sys\._getframe$", "reflection", "uses reflection"),
        (r"^(socket|urllib|http|requests|ssl|ftplib|smtplib)\.", "network", "network access"),
    ],
    "warning_calls": [
        (r"^time\.(monotonic|perf_counter|process_time)(_ns)?$", "clock", "reads a timer"),
        (r"^os\.(getenv|environ\.get)$", "env", "reads environment variables"),
        (r"^(builtins\.)?(getattr|setattr|delattr|vars|globals|locals)$", "reflection", "uses reflection"),
    ],
    "forbidden_new": [],
    "forbidden_imports": [
        (r"^(socket|socketserver|ssl|urllib|urllib3|http|requests|httpx|aiohttp|ftplib|smtplib|poplib|imaplib|"
         r"telnetlib|xmlrpc|asyncio|selectors)(\.|$)", "network", "network access"),
        (r"^(subprocess|multiprocessing|pty|concurrent)(\.|$)", "process", "executes a process"),
        (r"^(importlib|ctypes|cffi|inspect|marshal|pickle|shelve|code|codeop|runpy|gc)(\.|$)", "reflection",
         "uses reflection / dynamic code loading"),
    ],
    "file_open_calls": [
        r"^(builtins\.|io\.|codecs\.|os\.)?open$",
        r"^(pathlib\.)?(Pure)?(Posix)?Path$",
        r"^os\.(remove|unlink|rename|replace|mkdir|makedirs|rmdir|listdir|scandir|stat|truncate)$",
        r"^shutil\.\w+$",
    ],
    "allowed_import_prefixes": PY_STDLIB_ALLOWED,
    "import_separator": ".",
    "parse_dependencies": parse_python_dependencies,
    "allowed_dependencies": ["cobolrt"],
    "decimal_types_ok": ["Decimal", "decimal.Decimal", "CobolDecimal", "Fraction"],
    # Python's int is unbounded: never "too narrow"
    "integer_types": {"int": 10**6},
    "float_types": ["float", "complex"],
    "string_types": ["str", "bytes", "bytearray", "memoryview", "PicX"],
    "type_base": py_type_base,
}
