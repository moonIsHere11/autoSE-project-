"""T2b product harness + concrete replay driver (spec section 6, T2b.5; spike S2 §10).

For one unit we generate, in the candidate's package (so package-private fields are reachable):

* `T2bH_<P>.check()` — one nondet value per state variable, constrained to its PIC domain
  (`CProver.assume`), identical state loaded into the reference and the candidate, both units
  called, then `assert` equality of **every** mapped field (fields outside the unit's closure are
  asserted unchanged, so extra side effects are caught);
* `T2bH_<P>.reach()` — the same body ending in `assert false` (vacuity / reachability probe);
* `T2bR_<P>.main` — concrete replay: reads states (one per stdin line, space-separated integers in
  the harness input order), runs both sides with plain `java` and prints every field per side.

Candidate representations accepted (corpus/README + RUNTIME_API conventions): numeric fields as
`long`/`int`/`short`/`byte` holding the value scaled by 10^scale (arrays of those for OCCURS);
alphanumeric fields as `char[]` / `byte[]`. `String`, `StringBuilder`, `BigDecimal`, `double` …
are not checkable by JBMC (spike S2 §6.4–6.5) → NOT_APPLICABLE with that reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from verifier.langpacks.java.emit import EmittedRef, RefField

INT_TYPES = {"long": 18, "int": 9, "short": 4, "byte": 2}
ALNUM_TYPES = {"char[]": "char", "byte[]": "byte"}
MAX_ALNUM_STATE_CHARS = 400


class HarnessUnsupported(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class StateVar:
    """One nondet input (a long or a char) of the harness, in argument order."""

    name: str  # Java local, e.g. in_f_WS_A or in_f_WS_B_3
    cobol: str
    index: int | None  # OCCURS index (0-based) or None
    char_pos: int | None  # character position for alphanumerics
    kind: str  # num | alnum


@dataclass
class Slot:
    """A COBOL field present in the harness (reference and/or candidate side)."""

    cobol: str
    kind: str
    digits: int = 0
    scale: int = 0
    signed: bool = False
    length: int = 0
    occurs: int | None = None
    ref: RefField | None = None
    cand_field: str | None = None
    cand_type: str | None = None


@dataclass
class Harness:
    package: str
    harness_class: str
    replay_class: str
    harness_source: str
    replay_source: str
    state: list[StateVar]
    slots: list[Slot]
    assert_lines: dict[int, str] = field(default_factory=dict)  # harness line -> COBOL field
    notes: list[str] = field(default_factory=list)

    @property
    def check_function(self) -> str:
        return f"{self.package + '.' if self.package else ''}{self.harness_class}.check"

    @property
    def reach_function(self) -> str:
        return f"{self.package + '.' if self.package else ''}{self.harness_class}.reach"

    @property
    def qualified_harness(self) -> str:
        return f"{self.package + '.' if self.package else ''}{self.harness_class}"

    @property
    def qualified_replay(self) -> str:
        return f"{self.package + '.' if self.package else ''}{self.replay_class}"


def norm_type(t: str | None) -> str:
    return re.sub(r"\s+", "", t or "").replace("java.lang.", "")


def slot_for(cobol: str, ref: RefField | None, item_info: dict[str, Any], mapping: dict[str, Any] | None) -> Slot:
    """Build a slot; raises HarnessUnsupported if the candidate representation is not checkable."""
    kind = ref.kind if ref is not None else item_info["kind"]
    s = Slot(cobol, kind, ref.digits if ref else item_info.get("digits", 0), ref.scale if ref else item_info.get("scale", 0),
             ref.signed if ref else item_info.get("signed", False), ref.length if ref else item_info.get("length", 0),
             ref.occurs if ref else item_info.get("occurs"), ref)
    if mapping is None or not mapping.get("target"):
        return s
    t = norm_type(mapping.get("target_type"))
    base = t[:-2] if t.endswith("[]") and s.occurs and not (s.kind == "alnum" and t.count("[]") == 1) else t
    if s.occurs and not t.endswith("[]"):
        raise HarnessUnsupported(f"{cobol} OCCURS {s.occurs} is mapped to non-array {t or '?'}")
    if s.kind == "num":
        if base not in INT_TYPES:
            raise HarnessUnsupported(f"{cobol} is represented as `{t or '?'}` in the target; JBMC can only check "
                                     "integer-scaled numerics (long/int), not BigDecimal/String/double (spike S2)")
        if s.digits > INT_TYPES[base]:
            raise HarnessUnsupported(f"{cobol} has {s.digits} digits but target type `{base}` holds {INT_TYPES[base]}")
    else:
        elem = t[:-2] if s.occurs and t.endswith("[][]") else t
        if elem not in ALNUM_TYPES:
            raise HarnessUnsupported(f"{cobol} is represented as `{t or '?'}` in the target; JBMC can only check "
                                     "char[]/byte[] alphanumerics, not String/StringBuilder (spike S2 §6.5)")
    s.cand_field = mapping["target"]
    s.cand_type = t
    return s


def _cast(t: str) -> str:
    base = t.replace("[]", "")
    return f"({base}) " if base in ("int", "short", "byte") else ""


def build_harness(ref: EmittedRef, ref_method: str, cand_class: str, cand_method: str, package: str,
                  slots: list[Slot], unit_slug: str) -> Harness:
    """Generate harness + replay sources. `slots`: every field to load/compare (closure first)."""
    hname, rname = f"T2bH_{unit_slug}", f"T2bR_{unit_slug}"
    state: list[StateVar] = []
    load: list[str] = []
    checks: list[tuple[str, str]] = []  # (java boolean expr, cobol name)
    out_lines: list[str] = []
    n_chars = 0
    for s in slots:
        idxs: list[int | None] = list(range(s.occurs)) if s.occurs else [None]
        for k in idxs:
            sub = "" if k is None else f"[{k}]"
            sfx = "" if k is None else f"_{k}"
            base = re.sub(r"[^A-Za-z0-9]", "_", s.cobol)
            if s.kind == "num":
                v = f"in_{base}{sfx}"
                state.append(StateVar(v, s.cobol, k, None, "num"))
                load.append(f"long {v} = pic({s.digits}, {'true' if s.signed else 'false'});")
                if s.ref is not None:
                    load.append(f"r.{s.ref.jname}{sub} = {v};")
                if s.cand_field is not None:
                    assert s.cand_type is not None
                    load.append(f"c.{s.cand_field}{sub} = {_cast(s.cand_type)}{v};")
                    lhs = f"r.{s.ref.jname}{sub}" if s.ref is not None else v
                    checks.append((f"{lhs} == (long) c.{s.cand_field}{sub}", s.cobol))
                    out_lines.append(f'p("CAND", "{s.cobol}{sfx}", (long) c.{s.cand_field}{sub});')
                if s.ref is not None:
                    out_lines.append(f'p("REF", "{s.cobol}{sfx}", r.{s.ref.jname}{sub});')
                elif s.cand_field is not None:
                    out_lines.append(f'p("REF", "{s.cobol}{sfx}", {v});')  # outside the unit: unchanged
            else:
                n_chars += s.length
                if n_chars > MAX_ALNUM_STATE_CHARS:
                    raise HarnessUnsupported(f"alphanumeric state exceeds {MAX_ALNUM_STATE_CHARS} characters")
                elem = "char" if s.cand_type is None or s.cand_type.startswith("char") else "byte"
                for pos in range(s.length):
                    v = f"in_{base}{sfx}_c{pos}"
                    state.append(StateVar(v, s.cobol, k, pos, "alnum"))
                    load.append(f"char {v} = picX();")
                    if s.ref is not None:
                        load.append(f"r.{s.ref.jname}{sub}[{pos}] = {v};")
                    if s.cand_field is not None:
                        load.append(f"c.{s.cand_field}{sub}[{pos}] = ({elem}) {v};")
                        lhs = f"r.{s.ref.jname}{sub}[{pos}]" if s.ref is not None else v
                        checks.append((f"{lhs} == (char) c.{s.cand_field}{sub}[{pos}]", s.cobol))
                if s.cand_field is not None:
                    out_lines.append(f'px("CAND", "{s.cobol}{sfx}", c.{s.cand_field}{sub});')
                if s.ref is not None:
                    out_lines.append(f'px("REF", "{s.cobol}{sfx}", r.{s.ref.jname}{sub});')
                elif s.cand_field is not None:
                    init = ", ".join(f"in_{base}{sfx}_c{pos}" for pos in range(s.length))
                    out_lines.append(f'px("REF", "{s.cobol}{sfx}", new char[] {{{init}}});')
    if not checks:
        raise HarnessUnsupported("no COBOL field of the unit is mapped to a checkable target field")
    pkg = f"package {package};\n\n" if package else ""
    ref_q = ref.qualified
    pre = ["        " + x for x in load]
    calls = ["        boolean inModel = true;",
             "        try {",
             f"            r.{ref_method}();",
             f"        }} catch ({ref_q}.OutOfModel e) {{",
             "            inModel = false;",
             "        }",
             "        CProver.assume(inModel);",
             f"        c.{cand_method}();"]
    head = (pkg + "import org.cprover.CProver;\n\n"
            f"/** Generated T2b harness: {ref_q}.{ref_method} vs {cand_class}.{cand_method}. */\n"
            f"public final class {hname} {{\n"
            "    static long pic(int digits, boolean signed) {\n"
            "        long v = CProver.nondetLong();\n"
            "        long lim = 1L;\n"
            "        for (int i = 0; i < digits; i++) {\n"
            "            lim = lim * 10L;\n"
            "        }\n"
            "        CProver.assume(v < lim);\n"
            "        CProver.assume(signed ? v > -lim : v >= 0);\n"
            "        return v;\n"
            "    }\n\n"
            "    static char picX() {\n"
            "        char ch = CProver.nondetChar();\n"
            "        CProver.assume(ch >= ' ' && ch <= '~');\n"
            "        return ch;\n"
            "    }\n\n")
    lines = head.split("\n")
    lines.append("    public static void check() {")
    lines.append(f"        {ref_q} r = new {ref_q}();")
    lines.append(f"        {cand_class} c = new {cand_class}();")
    lines += pre + calls
    assert_lines: dict[int, str] = {}
    for expr, cobol in checks:
        lines.append(f'        assert {expr} : "EQ {cobol}";')
        assert_lines[len(lines)] = cobol
    lines += ["    }", "", "    public static void reach() {",
              f"        {ref_q} r = new {ref_q}();", f"        {cand_class} c = new {cand_class}();"]
    lines += pre + calls + ['        assert false : "REACH";', "    }", "}", ""]
    harness_src = "\n".join(lines)
    # ---- replay -----------------------------------------------------------------------------
    rload: list[str] = []
    for i, sv in enumerate(state):
        if sv.kind == "num":
            rload.append(f"long {sv.name} = a[{i}];")
        else:
            rload.append(f"char {sv.name} = (char) a[{i}];")
    rbody = [x for x in load if not x.startswith(("long in_", "char in_"))]
    replay_src = (pkg + "import java.io.BufferedReader;\nimport java.io.InputStreamReader;\n\n"
                  f"/** Generated T2b concrete replay for {hname} (plain java, no JBMC). */\n"
                  f"public final class {rname} {{\n"
                  "    static final StringBuilder OUT = new StringBuilder();\n"
                  "    static void p(String side, String f, long v) {\n"
                  "        OUT.append(side).append('\\t').append(f).append('\\t').append(v).append('\\n');\n"
                  "    }\n"
                  "    static void px(String side, String f, char[] v) {\n"
                  "        OUT.append(side).append('\\t').append(f).append('\\t');\n"
                  "        for (int i = 0; i < v.length; i++) { OUT.append(i == 0 ? \"\" : \",\").append((int) v[i]); }\n"
                  "        OUT.append('\\n');\n"
                  "    }\n"
                  "    static void px(String side, String f, byte[] v) {\n"
                  "        char[] c = new char[v.length];\n"
                  "        for (int i = 0; i < v.length; i++) { c[i] = (char) (v[i] & 0xff); }\n"
                  "        px(side, f, c);\n"
                  "    }\n"
                  "    public static void main(String[] args) throws Exception {\n"
                  "        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));\n"
                  "        String line;\n"
                  "        int k = 0;\n"
                  "        while ((line = in.readLine()) != null) {\n"
                  "            line = line.trim();\n"
                  "            if (line.isEmpty()) { continue; }\n"
                  "            String[] parts = line.split(\" \");\n"
                  "            long[] a = new long[parts.length];\n"
                  "            for (int i = 0; i < parts.length; i++) { a[i] = Long.parseLong(parts[i]); }\n"
                  "            OUT.append(\"CASE\\t\").append(k++).append('\\n');\n"
                  + "".join("            " + x + "\n" for x in rload)
                  + f"            {ref_q} r = new {ref_q}();\n"
                  f"            {cand_class} c = new {cand_class}();\n"
                  + "".join("            " + x + "\n" for x in rbody)
                  + "            boolean refOk = true;\n"
                  f"            try {{ r.{ref_method}(); }} catch ({ref_q}.OutOfModel e) {{ refOk = false; "
                  "OUT.append(\"REFOUT\\n\"); }\n"
                  "            catch (Throwable t) { refOk = false; OUT.append(\"REFTHROW\\t\").append(t.getClass().getName())"
                  ".append('\\n'); }\n"
                  f"            try {{ c.{cand_method}(); }} catch (Throwable t) {{ OUT.append(\"CANDTHROW\\t\")"
                  ".append(t.getClass().getName()).append('\\n'); }\n"
                  "            if (refOk) {\n"
                  + "".join("                " + x + "\n" for x in out_lines)
                  + "            }\n"
                  "        }\n"
                  "        System.out.print(OUT);\n"
                  "        System.out.flush();\n"
                  "    }\n"
                  "}\n")
    return Harness(package, hname, rname, harness_src, replay_src, state, slots, assert_lines)


# ---------------------------------------------------------------------------------------------
@dataclass
class ReplayCase:
    ref: dict[str, str]
    cand: dict[str, str]
    ref_out_of_model: bool = False
    ref_throw: str | None = None
    cand_throw: str | None = None

    def differences(self) -> list[tuple[str, str, str]]:
        """(field, ref value, cand value) for every compared field that differs."""
        out = []
        for k, v in self.ref.items():
            if k in self.cand and self.cand[k] != v:
                out.append((k, v, self.cand[k]))
        return out

    @property
    def mismatch(self) -> bool:
        if self.ref_out_of_model or self.ref_throw:
            return False
        return bool(self.cand_throw) or bool(self.differences())


def parse_replay(text: str) -> list[ReplayCase]:
    cases: list[ReplayCase] = []
    cur: ReplayCase | None = None
    for line in text.splitlines():
        parts = line.split("\t")
        if parts[0] == "CASE":
            cur = ReplayCase({}, {})
            cases.append(cur)
        elif cur is None:
            continue
        elif parts[0] == "REF" and len(parts) == 3:
            cur.ref[parts[1]] = parts[2]
        elif parts[0] == "CAND" and len(parts) == 3:
            cur.cand[parts[1]] = parts[2]
        elif parts[0] == "REFOUT":
            cur.ref_out_of_model = True
        elif parts[0] == "REFTHROW":
            cur.ref_throw = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "CANDTHROW":
            cur.cand_throw = parts[1] if len(parts) > 1 else "?"
    return cases


def state_line(h: Harness, values: dict[str, int]) -> str:
    """Replay input line from JBMC trace inputs (missing inputs default to 0 / space)."""
    vals = []
    for sv in h.state:
        default = 32 if sv.kind == "alnum" else 0
        vals.append(str(values.get(sv.name, default)))
    return " ".join(vals)
