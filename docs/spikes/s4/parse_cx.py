"""Prototype of the verifier's CrossHair output parser + concrete replay.

usage (inside the container, cwd /w):  python parse_cx.py
Parses every out/q*.out produced by inner.sh, extracts counterexample arguments with `ast`
(never eval), and for diffbehavior results replays both functions concretely to confirm.
"""
import ast
import glob
import importlib
import re
import sys

GIVEN = re.compile(r"^Given: \((?P<args>.*)\),$")
CHECK = re.compile(r"^(?P<file>.+?):(?P<line>\d+): (?P<sev>error|info|warning): (?P<msg>.*)$")
WHICH_RETURNS = re.compile(r" \(which returns .*\)$")


def parse_kwargs(text: str) -> dict:
    """'a=0, b=-1' -> {'a': 0, 'b': -1}; raises ValueError if not literal (e.g. dataclass repr)."""
    call = ast.parse(f"f({text})", mode="eval").body
    assert isinstance(call, ast.Call) and not call.args
    return {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}


def parse_call(text: str):
    """'fn(-1, -9999999) (which returns -10000000)' -> ('fn', [-1, -9999999])."""
    text = WHICH_RETURNS.sub("", text)
    call = ast.parse(text, mode="eval").body
    assert isinstance(call, ast.Call)
    return call.func.id, [ast.literal_eval(a) for a in call.args]


def load(qualname: str):
    mod, _, fn = qualname.rpartition(".")
    return getattr(importlib.import_module(mod), fn)


def outcome(f, kwargs):
    try:
        return ("ok", f(**kwargs))
    except Exception as e:
        return ("exc", type(e).__name__)


def diffbehavior_report(path: str, cmd: list):
    lines = open(path).read().splitlines()
    cxs = []
    for ln in lines:
        m = GIVEN.match(ln)
        if m:
            try:
                cxs.append(parse_kwargs(m.group("args")))
            except (ValueError, SyntaxError, AssertionError) as e:
                cxs.append(f"UNPARSEABLE ({type(e).__name__}): {m.group('args')}")
    if not cxs:
        return "no counterexample" if lines and lines[0].startswith("No differences found.") else "no Given: lines"
    out = []
    f1, f2 = load(cmd[0]), load(cmd[1])
    for cx in cxs:
        if isinstance(cx, str):
            out.append(cx)
            continue
        o1, o2 = outcome(f1, cx), outcome(f2, cx)
        out.append(f"{cx} -> replay {'CONFIRMED' if o1 != o2 else 'NOT REPRODUCED'}: {o1} vs {o2}")
    return "; ".join(out)


def check_report(path: str):
    res = []
    for ln in open(path).read().splitlines():
        m = CHECK.match(ln)
        if not m or m.group("sev") != "error":
            continue
        msg = m.group("msg")
        if " when calling " not in msg:
            res.append(f"line {m.group('line')}: {msg}")
            continue
        reason, _, call = msg.rpartition(" when calling ")
        try:
            fn, args = parse_call(call)
            res.append(f"line {m.group('line')}: {reason!r} at {fn}{tuple(args)}")
        except (ValueError, SyntaxError, AssertionError) as e:
            res.append(f"line {m.group('line')}: UNPARSEABLE ({type(e).__name__}) {call}")
    return "; ".join(res) or "no errors"


if __name__ == "__main__":
    sys.path.insert(0, ".")
    # recover each experiment's command from inner.sh ("X <name> <cmd...>", shell vars expanded)
    shvars = {"D": "crosshair diffbehavior", "R": "cobol_ref", "L": "llm_variants",
              "H": "harness_dom", "S": "state_toys", "M": "misc_toys", "C": "contracts_toys"}
    cmds = {}
    for ln in open("inner.sh").read().splitlines():
        parts = ln.split()
        if len(parts) > 2 and parts[0] == "X":
            cmd = re.sub(r"\$(\w+)", lambda m: shvars.get(m.group(1), m.group(0)), " ".join(parts[2:]))
            if "$i" in parts[1]:
                for i in "123":
                    cmds[parts[1].replace("$i", i)] = cmd.split()
            else:
                cmds[parts[1]] = cmd.split()
    for path in sorted(glob.glob("out/q*.out")):
        name = path[4:-4]
        cmd = cmds.get(name)
        if not cmd:
            continue
        if cmd[1] == "diffbehavior":
            fns = [a for a in cmd[2:] if not a.startswith("-") and "." in a][:2]
            try:
                print(f"{name}: {diffbehavior_report(path, fns)}")
            except Exception as e:  # e.g. module/function cannot be loaded for replay
                print(f"{name}: replay failed: {type(e).__name__}: {e}")
        else:
            print(f"{name}: {check_report(path)}")
