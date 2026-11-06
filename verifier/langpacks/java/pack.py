"""Java language pack: build (javac / manifest), tree-sitter index, resolution, run command."""

from __future__ import annotations

import re
import shlex
import time
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
from verifier.manifest import ProgramMap, camel, loose, pascal
from verifier.report.schema import Finding
from verifier.sandbox.docker_runner import Mount

BUILD_DIR = ".verifier-build"
JVM_FLAGS = "-Xshare:auto -XX:TieredStopAtLevel=1 -XX:-UsePerfData -Xss16m"
COBOLRT_JAR = "/opt/cobolrt/java/cobolrt.jar"
TEST_DIR_MARKERS = ("/src/test/", "/test/", "/tests/")

_JAVAC_DIAG = re.compile(r"^(?P<file>[^\s:][^:\n]*\.java):(?P<line>\d+): (?P<sev>error|warning): (?P<msg>.*)$", re.M)
_MAVEN_DIAG = re.compile(
    r"^\[(?P<sev>ERROR|WARNING)\] (?P<file>/[^:\n]+\.java):\[(?P<line>\d+),(?P<col>\d+)\] (?P<msg>.*)$", re.M
)


def _is_test_path(rel_path: str) -> bool:
    p = "/" + rel_path
    return any(m in p for m in TEST_DIR_MARKERS)


class JavaPack(LangPack):
    name = "java"
    file_suffixes = (".java",)

    # ------------------------------------------------------------------------------------------
    def sources(self, root: Path) -> list[str]:
        out = []
        for p in sorted(root.rglob("*.java")):
            r = p.relative_to(root).as_posix()
            if r.startswith(BUILD_DIR) or _is_test_path(r):
                continue
            out.append(r)
        return out

    def build(self, ctx: PackContext) -> BuildResult:
        tgt = ctx.target_root
        m = ctx.manifest
        start = time.monotonic()
        if m is not None and m.build is not None:
            workdir = m.build.workdir.strip("/") or "."
            command = m.build.command
            script = f"cd /tgt/{shlex.quote(workdir)} && {command}"
        else:
            srcs = self.sources(tgt)
            if not srcs:
                return BuildResult(False, "javac", "no Java sources found", 0.0, [
                    Finding(check="T0a.build", severity="ERROR", message="no Java sources found in the target repo")
                ])
            (tgt / BUILD_DIR / "classes").mkdir(parents=True, exist_ok=True)
            (tgt / BUILD_DIR / "sources.txt").write_text("\n".join(srcs) + "\n", "utf-8")
            command = (
                f"javac -encoding UTF-8 -Xmaxerrs 50 -Xlint:none -d {BUILD_DIR}/classes "
                f"-cp {COBOLRT_JAR} @{BUILD_DIR}/sources.txt"
            )
            script = f"cd /tgt && {command}"
        mounts = [Mount(tgt, "/tgt", read_only=False)]
        if ctx.runtime_dir is not None:
            mounts.append(Mount(ctx.runtime_dir, "/opt/cobolrt", read_only=True))
        res = ctx.runner.run(
            ["bash", "-c", script],
            mounts=mounts,
            network=ctx.config.allow_build_network,
            timeout_s=ctx.config.limits.build_timeout_s,
        )
        out = res.text()
        diags = parse_diagnostics(out, tgt)
        ok = res.ok and not any(d.severity == "ERROR" for d in diags)
        if not res.ok and not diags:
            diags.append(Finding(check="T0a.build", severity="ERROR",
                                 message=f"build command failed (exit {res.returncode}): {out.strip()[-1500:]}"))
        return BuildResult(ok, command, out, time.monotonic() - start, diags, res.timed_out)

    # ------------------------------------------------------------------------------------------
    def index(self, root: Path) -> SymbolIndex:
        idx = SymbolIndex()
        parser = ts.parser_for("java")
        for p in sorted(root.rglob("*.java")):
            r = p.relative_to(root).as_posix()
            if r.startswith(BUILD_DIR):
                continue
            data = p.read_bytes()
            idx.files[r] = data
            tree = parser.parse(data)
            if ts.has_error(tree.root_node):
                idx.parse_errors.append(f"{r}: tree-sitter reports syntax errors")
            _index_java(tree.root_node, r, idx, is_test=_is_test_path(r))
        return idx

    def resolve_program(
        self, ctx: PackContext, index: SymbolIndex, prog: Program, entry: ProgramMap | None
    ) -> ResolvedProgram:
        notes: list[str] = []
        source = "manifest" if entry is not None else "convention"
        type_sym: TypeSym | None = None
        if entry is not None and entry.class_:
            exact = [t for t in index.types if t.qualified == entry.class_]
            cands = exact or index.find_type(entry.class_)
            if not cands:
                notes.append(f"manifest class {entry.class_} not found in the target code")
        else:
            cands = index.find_type(pascal(prog.program_id)) or [
                t for t in index.types if loose(t.name) == loose(prog.program_id)
            ]
        if cands:
            cands = sorted(cands, key=lambda t: (not t.has_main, t.qualified))
            type_sym = cands[0]
            if len(cands) > 1:
                notes.append(f"several candidate classes for {prog.program_id}: {[c.qualified for c in cands]}; using {type_sym.qualified}")
        run_cmd: str | None = None
        if entry is not None and entry.run is not None:
            run_cmd = rewrite_run_command(entry.run.command, ctx.target_root)
        elif type_sym is not None:
            cp = f"/tgt/{BUILD_DIR}/classes"
            if ctx.manifest is not None and ctx.manifest.build is not None:
                cp = "/tgt/target/classes"
                notes.append("manifest has a build command but no run command; assuming Maven layout target/classes")
            run_cmd = f"java {JVM_FLAGS} -cp {cp}:{COBOLRT_JAR} {type_sym.qualified}"
        files: dict[str, str] = {}
        for sel in prog.selects:
            if sel.assign and sel.assign_kind in ("literal", "name"):
                files[sel.name] = sel.assign
        if entry is not None:
            for file_map in entry.files:
                files[file_map.cobol_select.upper()] = file_map.path
        units: dict[str, str | None] = {}
        locs: dict[str, MethodSym | None] = {}
        explicit = {u.cobol_paragraph.upper(): u.target_symbol for u in entry.units} if entry else {}
        methods = type_sym.methods if type_sym is not None else []
        for para in prog.paragraphs:
            want = explicit.get(para.name) or camel(para.name)
            m = next((mm for mm in methods if mm.name == want), None) or next(
                (mm for mm in methods if loose(mm.name) == loose(want)), None
            )
            units[para.name] = m.name if m else (explicit.get(para.name))
            locs[para.name] = m
        fields: dict[str, dict[str, Any]] = {}
        fsyms = type_sym.fields if type_sym is not None else []
        if entry is not None and entry.fields:
            for fm in entry.fields:
                f = next((x for x in fsyms if x.name == fm.target), None)
                fields[fm.cobol.upper()] = {
                    "target": fm.target, "declared": fm.declared.model_dump(exclude_none=True) if fm.declared else None,
                    "target_type": fm.target_type or (f.type_text if f else None),
                    "location": (f.file, f.line) if f else None, "source": "manifest",
                }
        for item in prog.all_items():
            if item.is_filler or not item.is_elementary or item.name in fields:
                continue
            want = camel(item.name)
            f = next((x for x in fsyms if x.name == want), None) or next(
                (x for x in fsyms if loose(x.name) == loose(item.name)), None
            )
            if f is not None:
                fields[item.name] = {"target": f.name, "declared": None, "target_type": f.type_text,
                                     "location": (f.file, f.line), "source": "convention"}
        if entry is not None and (not entry.fields or not entry.units):
            source = "mixed"
        return ResolvedProgram(prog.program_id, prog.source_file, type_sym, run_cmd, files, units, locs,
                               fields, source, notes)

    def run_command(self, ctx: PackContext, resolved: ResolvedProgram) -> list[str] | NotApplicable:
        if resolved.run_command is None:
            return NotApplicable(f"no Java class found for program {resolved.program_id} "
                                 f"(convention: class {pascal(resolved.program_id)} with main)")
        return ["sh", "-c", resolved.run_command + ' "$@"', "sh"]

    def static_rules(self) -> dict[str, Any]:
        return JAVA_RULES


# ---------------------------------------------------------------------------------------------
def rewrite_run_command(cmd: str, target_root: Path) -> str:
    """D7: make relative paths that exist in the target repo absolute under /tgt."""
    out = []
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    prev = ""
    for tok in parts:
        if prev in ("-cp", "-classpath", "--class-path"):
            entries = []
            for e in tok.split(":"):
                entries.append(_abs_if_exists(e, target_root))
            out.append(":".join(entries))
        else:
            out.append(_abs_if_exists(tok, target_root))
        prev = tok
    return " ".join(shlex.quote(x) if not x.startswith("$") else x for x in out)


def _abs_if_exists(tok: str, root: Path) -> str:
    if not tok or tok.startswith(("/", "-", "$")):
        return tok.replace("$TARGET_ROOT", "/tgt")
    candidate = root / tok
    if candidate.exists():
        return f"/tgt/{tok}"
    return tok


def parse_diagnostics(output: str, root: Path) -> list[Finding]:
    diags: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for rx in (_JAVAC_DIAG, _MAVEN_DIAG):
        for m in rx.finditer(output):
            f = m.group("file")
            for prefix in ("/tgt/", "./"):
                if f.startswith(prefix):
                    f = f[len(prefix) :]
            ln = int(m.group("line"))
            sev: Literal["ERROR", "WARNING"] = "ERROR" if m.group("sev").upper() == "ERROR" else "WARNING"
            key = (f, ln, m.group("msg"))
            if key in seen:
                continue
            seen.add(key)
            diags.append(Finding(check="T0a.build", severity=sev, message=m.group("msg").strip(),
                                 file=f, line=ln, excerpt=excerpt(root / f, ln)))
    return diags


def excerpt(path: Path, ln: int, ctx: int = 2) -> str | None:
    try:
        lines = path.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    lo, hi = max(1, ln - ctx), min(len(lines), ln + ctx)
    return "\n".join(f"{'>' if i == ln else ' '}{i:5d} | {lines[i - 1]}" for i in range(lo, hi + 1))


# ---------------------------------------------------------------------------------------------
# tree-sitter indexing
# ---------------------------------------------------------------------------------------------
_CATCH_ALL = {"Exception", "Throwable", "RuntimeException", "Error", "java.lang.Exception", "java.lang.Throwable"}


def _index_java(root: Node, file: str, idx: SymbolIndex, is_test: bool) -> None:
    package = ""
    for child in root.children:
        if child.type == "package_declaration":
            package = ts.text(child).replace("package", "").strip().rstrip(";").strip()
        if child.type == "import_declaration":
            imp = ts.text(child).replace("import", "").replace("static ", "").strip().rstrip(";").strip()
            idx.imports.append((imp, file, ts.line(child)))

    def visit_type(node: Node, outer: str) -> None:
        name = ts.text(node.child_by_field_name("name"))
        qualified = f"{outer}.{name}" if outer else (f"{package}.{name}" if package else name)
        tsym = TypeSym(name, qualified, file, ts.line(node))
        body = node.child_by_field_name("body")
        if body is not None:
            for member in body.named_children:
                if member.type == "field_declaration":
                    ftype = ts.text(member.child_by_field_name("type"))
                    for decl in member.children_by_field_name("declarator"):
                        val = decl.child_by_field_name("value")
                        tsym.fields.append(FieldSym(ts.text(decl.child_by_field_name("name")), ftype, file,
                                                    ts.line(decl), ts.text(val) if val else None))
                elif member.type in ("method_declaration", "constructor_declaration"):
                    mname = ts.text(member.child_by_field_name("name"))
                    mods = ""
                    for c in member.children:
                        if c.type == "modifiers":
                            mods = ts.text(c)
                    pnode = member.child_by_field_name("parameters")
                    plist = [ts.text(p) for p in pnode.named_children] if pnode is not None else []
                    tsym.methods.append(MethodSym(mname, file, ts.line(member), ts.end_line(member), plist,
                                                  "static" in mods))
                    if mname == "main" and "static" in mods:
                        tsym.has_main = True
                elif member.type in ("class_declaration", "enum_declaration", "record_declaration"):
                    visit_type(member, qualified)
            if node.type == "record_declaration":
                rparams = node.child_by_field_name("parameters")
                if rparams is not None:
                    for p in rparams.named_children:
                        tsym.fields.append(FieldSym(ts.text(p.child_by_field_name("name")),
                                                    ts.text(p.child_by_field_name("type")), file, ts.line(p)))
        if not is_test:
            idx.types.append(tsym)

    for child in root.named_children:
        if child.type in ("class_declaration", "enum_declaration", "record_declaration", "interface_declaration"):
            visit_type(child, "")

    if is_test:
        return
    for n in ts.walk(root):
        t = n.type
        if t in ("decimal_integer_literal", "hex_integer_literal", "decimal_floating_point_literal"):
            raw = ts.text(n)
            val = ts.normalise_number(raw)
            if val is not None:
                parent = n.parent
                if parent is not None and parent.type == "unary_expression" and ts.text(parent).startswith("-"):
                    val = "0" if val == "0" else ("-" + val if not val.startswith("-") else val)
                idx.literals.append(Literal_("float" if "floating" in t else "int", raw, val, file, ts.line(n)))
        elif t == "string_literal":
            raw = ts.text(n)
            inner = raw[1:-1] if raw.startswith('"') and not raw.startswith('"""') else raw.strip('"')
            idx.literals.append(Literal_("str", raw, ts.unescape(inner), file, ts.line(n)))
        elif t == "method_invocation":
            obj = n.child_by_field_name("object")
            name = ts.text(n.child_by_field_name("name"))
            callee = f"{ts.text(obj)}.{name}" if obj is not None else name
            args = n.child_by_field_name("arguments")
            idx.calls.append(CallSite(callee, file, ts.line(n), *_args(args)))
        elif t == "object_creation_expression":
            typ = ts.text(n.child_by_field_name("type"))
            args = n.child_by_field_name("arguments")
            idx.news.append(CallSite(typ, file, ts.line(n), *_args(args)))
        elif t == "catch_clause":
            param = next((c for c in n.named_children if c.type == "catch_formal_parameter"), None)
            types = []
            if param is not None:
                for c in ts.walk(param):
                    if c.type in ("type_identifier", "scoped_type_identifier") and c.parent is not None and c.parent.type in ("catch_type", "catch_formal_parameter"):
                        types.append(ts.text(c))
            body = n.child_by_field_name("body")
            swallows = False
            if any(x in _CATCH_ALL for x in types) and body is not None:
                rethrows = any(c.type == "throw_statement" for c in ts.walk(body))
                exits = any(c.type == "method_invocation" and ts.text(c.child_by_field_name("name")) in ("exit", "halt")
                            for c in ts.walk(body))
                swallows = not (rethrows or exits)
            idx.catches.append(CatchSite(types, file, ts.line(n), swallows))
        elif t == "floating_point_type" or (t == "type_identifier" and ts.text(n) in ("Double", "Float")):
            idx.float_uses.append((ts.text(n), file, ts.line(n)))


def _args(args: Node | None) -> tuple[list[str], list[str]]:
    if args is None:
        return [], []
    texts = [ts.text(a) for a in args.named_children]
    strs = []
    for a in args.named_children:
        if a.type == "string_literal":
            raw = ts.text(a)
            strs.append(ts.unescape(raw[1:-1]))
    return texts, strs


# ---------------------------------------------------------------------------------------------
# static rule tables (consumed by tiers/t0_static.py)
# ---------------------------------------------------------------------------------------------
JAVA_RULES: dict[str, Any] = {
    "forbidden_calls": [
        (r"(^|\.)System\.currentTimeMillis$", "clock", "reads the wall clock (use the injected clock)"),
        (r"(^|\.)(LocalDate|LocalDateTime|LocalTime|Instant|ZonedDateTime|OffsetDateTime|Year|YearMonth)\.now$", "clock",
         "reads the wall clock (use the injected clock)"),
        (r"(^|\.)Clock\.system(UTC|DefaultZone)?$", "clock", "reads the system clock"),
        (r"(^|\.)Calendar\.getInstance$", "clock", "reads the wall clock"),
        (r"(^|\.)Math\.random$", "rng", "uses an uninjected random source"),
        (r"(^|\.)ThreadLocalRandom\.current$", "rng", "uses an uninjected random source"),
        (r"(^|\.)UUID\.randomUUID$", "rng", "uses an uninjected random source"),
        (r"(^|\.)Runtime\.getRuntime\(\)\.exec$", "process", "executes a process"),
        (r"(^|\.)Class\.forName$", "reflection", "uses reflection"),
        (r"\.(getDeclaredMethod|getDeclaredMethods|getDeclaredField|getDeclaredFields|setAccessible|getDeclaredConstructor)$",
         "reflection", "uses reflection"),
    ],
    "warning_calls": [
        (r"(^|\.)System\.nanoTime$", "clock", "reads a timer"),
        (r"(^|\.)System\.getenv$", "env", "reads environment variables"),
    ],
    "forbidden_new": [
        (r"^(java\.util\.)?Random$", "rng", "uses an uninjected random source"),
        (r"^(java\.security\.)?SecureRandom$", "rng", "uses an uninjected random source"),
        (r"^(java\.util\.)?Date$", "clock", "new Date() reads the wall clock"),
        (r"^(java\.lang\.)?ProcessBuilder$", "process", "executes a process"),
        (r"^(java\.net\.)?(Socket|ServerSocket|DatagramSocket|URL|URI|HttpURLConnection)$", "network", "network access"),
    ],
    "forbidden_imports": [
        (r"^java\.net(\.|$)", "network", "network access"),
        (r"^javax\.net(\.|$)", "network", "network access"),
        (r"^java\.rmi(\.|$)", "network", "network access"),
        (r"^java\.nio\.channels\.(Socket|ServerSocket|Datagram)", "network", "network access"),
        (r"^java\.lang\.reflect(\.|$)", "reflection", "uses reflection"),
        (r"^javax\.script(\.|$)", "process", "dynamic code execution"),
        (r"^java\.lang\.invoke(\.|$)", "reflection", "uses reflection"),
    ],
    "file_open_calls": [
        r"^(java\.io\.)?(File|FileReader|FileWriter|FileInputStream|FileOutputStream|RandomAccessFile|PrintWriter|PrintStream|Scanner)$",
        r"(^|\.)(Paths\.get|Path\.of)$",
        r"(^|\.)Files\.(newBufferedReader|newBufferedWriter|readAllLines|readAllBytes|readString|write|writeString|lines|newInputStream|newOutputStream|exists|delete|copy|move)$",
    ],
    "allowed_import_prefixes": [
        "java.lang", "java.util", "java.io", "java.nio.file", "java.nio.charset", "java.nio.ByteBuffer",
        "java.nio.ByteOrder", "java.nio", "java.math", "java.text", "java.time", "java.util.function",
        "java.util.stream", "cobolrt", "org.cprover",
    ],
    "decimal_types_ok": ["BigDecimal", "java.math.BigDecimal", "CobolDecimal", "cobolrt.CobolDecimal"],
    "integer_types": {"byte": 2, "Byte": 2, "short": 4, "Short": 4, "int": 9, "Integer": 9, "long": 18, "Long": 18,
                      "BigInteger": 10**6, "java.math.BigInteger": 10**6},
    "float_types": ["float", "double", "Float", "Double"],
    "string_types": ["String", "char[]", "StringBuilder", "byte[]", "PicX", "cobolrt.PicX", "CharSequence"],
}
