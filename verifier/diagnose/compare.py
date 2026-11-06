"""Byte comparison of one case and decoding of the differences into field-level values.

Comparison is on raw bytes (stdout, every file left in the working directory, return code); no
normalisation unless a normaliser is explicitly enabled (and then it is reported).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from verifier.cobol.analysis import DisplaySite, FileChannel
from verifier.cobol.datadiv import DataItem
from verifier.cobol.syntax import Program
from verifier.cobol.trace import TraceEvent, display_events
from verifier.inputs.encode import decode_record, display_value
from verifier.report.schema import FieldDiff
from verifier.sandbox.batch import CaseRun

SEVERITY = {"TARGET_TIMEOUT": 1, "TARGET_CRASH": 1, "RETURN_CODE": 2, "LINE_COUNT": 3, "FILE_MISSING": 3,
            "FILE_EXTRA": 3, "RECORD_COUNT": 3, "VALUE_MISMATCH": 4, "STDOUT_MISMATCH": 4, "FILE_CONTENT": 4}


@dataclass
class Mismatch:
    kind: str
    location: str
    signature: str
    diffs: list[FieldDiff] = field(default_factory=list)
    items: list[DataItem] = field(default_factory=list)
    site: DisplaySite | None = None
    output_line: int | None = None  # 0-based stdout line index
    detail: str = ""

    @property
    def severity(self) -> int:
        return SEVERITY.get(self.kind, 5)


@dataclass
class CompareCtx:
    program: Program
    sites: dict[tuple[str, int], DisplaySite]
    output_files: dict[str, FileChannel]
    normalisers: list[str]


def _norm(data: bytes, normalisers: list[str]) -> bytes:
    if "trailing_whitespace" in normalisers:
        data = b"\n".join(line.rstrip() for line in data.split(b"\n"))
    if "final_newline" in normalisers:
        data = data.rstrip(b"\n") + b"\n" if data else data
    return data


def _show(b: bytes, limit: int = 160) -> str:
    s = b.decode("latin-1")
    out = "".join(c if 32 <= ord(c) < 127 else f"\\x{ord(c):02x}" for c in s)
    return out if len(out) <= limit else out[:limit] + "…"


def line_sites(ctx: CompareCtx, events: list[TraceEvent]) -> list[list[DisplaySite]]:
    """For each stdout line, the DISPLAY statement(s) that produced it (from the COBOL trace)."""
    lines: list[list[DisplaySite]] = []
    pending: list[DisplaySite] = []
    for ev in display_events(events, ctx.program):
        site = next((s for (f, ln), s in ctx.sites.items() if ln == ev.line and f.rsplit("/", 1)[-1].lower() == ev.file.rsplit("/", 1)[-1].lower()), None)
        if site is None:
            pending = []
            lines.append([])
            continue
        if site.upon and site.upon not in ("CONSOLE", "SYSOUT", "STDOUT"):
            continue
        pending.append(site)
        if not site.no_advancing:
            lines.append(pending)
            pending = []
    if pending:
        lines.append(pending)
    return lines


def _split_line(sites: list[DisplaySite], text: str, strict: bool) -> list[tuple[str, DataItem | None, str]] | None:
    """Split a displayed line into (operand text, item, value) using the operand layout."""
    ops = [op for s in sites for op in s.operands]
    if not ops:
        return None
    pattern = ""
    for k, op in enumerate(ops):
        last = k == len(ops) - 1
        if op.kind == "literal":
            pattern += re.escape(op.text)
        elif op.length is not None and strict:
            pattern += f"(.{{{op.length}}})"
        else:
            pattern += "(.*)" if last else "(.*?)"
    m = re.fullmatch(pattern, text, re.S)
    if not m:
        return None
    out = []
    gi = 1
    for op in ops:
        if op.kind == "literal":
            continue
        out.append((op.text, op.item, m.group(gi)))
        gi += 1
    return out


def compare(exp: CaseRun, act: CaseRun, ctx: CompareCtx) -> list[Mismatch]:
    out: list[Mismatch] = []
    if act.timed_out and not exp.timed_out:
        return [Mismatch("TARGET_TIMEOUT", "process", "TARGET_TIMEOUT", detail="target exceeded the case timeout")]
    exc = re.search(rb"Exception in thread \"main\" ([\w.$]+)|Traceback|panic: ", act.stderr)
    if act.return_code != exp.return_code:
        if exc:
            name = exc.group(1).decode() if exc.group(1) else exc.group(0).decode()
            return [Mismatch("TARGET_CRASH", "process", f"TARGET_CRASH {name}",
                             detail=_show(act.stderr[-600:], 600))]
        out.append(Mismatch("RETURN_CODE", "return code", "RETURN_CODE",
                            [FieldDiff(location="return code", expected=str(exp.return_code), actual=str(act.return_code))]))
    out.extend(_compare_stdout(exp, act, ctx))
    out.extend(_compare_files(exp, act, ctx))
    return out


def _compare_stdout(exp: CaseRun, act: CaseRun, ctx: CompareCtx) -> list[Mismatch]:
    e, a = _norm(exp.stdout, ctx.normalisers), _norm(act.stdout, ctx.normalisers)
    if e == a:
        return []
    el, al = e.split(b"\n"), a.split(b"\n")
    events = _events(exp)
    sites_per_line = line_sites(ctx, events) if events else []
    k = next((i for i in range(min(len(el), len(al))) if el[i] != al[i]), None)
    if k is None:
        n_common = min(len(el), len(al))
        missing = len(el) > len(al)
        return [Mismatch("LINE_COUNT", f"stdout after line {n_common}", "LINE_COUNT stdout",
                         [FieldDiff(location="stdout line count", expected=str(len(el) - 1), actual=str(len(al) - 1))],
                         output_line=n_common, detail="target output is missing lines" if missing else "target prints extra lines")]
    sites = sites_per_line[k] if k < len(sites_per_line) else []
    et, at = el[k].decode("latin-1"), al[k].decode("latin-1")
    loc_site = f" (DISPLAY at {sites[0].file}:{sites[0].line})" if sites else ""
    location = f"stdout line {k + 1}{loc_site}"
    diffs: list[FieldDiff] = []
    items: list[DataItem] = []
    if sites:
        es = _split_line(sites, et, strict=True)
        as_ = _split_line(sites, at, strict=True) or _split_line(sites, at, strict=False)
        if es and as_ and len(es) == len(as_):
            for (otext, item, ev), (_o2, _i2, av) in zip(es, as_, strict=True):
                if ev != av:
                    fld = item.name if item else otext
                    diffs.append(FieldDiff(location=location, field=fld, pic=item.pic_text() if item else None,
                                           expected=ev, actual=av))
                    if item is not None:
                        items.append(item)
    if not diffs:
        diffs.append(FieldDiff(location=location, expected=_show(el[k]), actual=_show(al[k])))
    if items:
        sig = f"VALUE_MISMATCH stdout:{sites[0].file}:{sites[0].line}:{items[0].name}"
        kind = "VALUE_MISMATCH"
    else:
        sig = f"STDOUT_MISMATCH stdout:{sites[0].file}:{sites[0].line}" if sites else f"STDOUT_MISMATCH stdout:line{k + 1}"
        kind = "STDOUT_MISMATCH"
    return [Mismatch(kind, location, sig, diffs, items, sites[0] if sites else None, k)]


def _events(run: CaseRun) -> list[TraceEvent]:
    from verifier.cobol.trace import parse_trace

    return parse_trace(run.trace) if run.trace else []


def _records(data: bytes, fc: FileChannel) -> list[bytes]:
    assert fc.fd is not None
    size = fc.fd.record_size
    if fc.select.organization == "LINE SEQUENTIAL":
        lines = data.split(b"\n")
        if lines and lines[-1] == b"":
            lines = lines[:-1]
        return [ln.ljust(size, b" ") for ln in lines]
    return [data[i : i + size] for i in range(0, len(data), size)] if size else [data]


def _compare_files(exp: CaseRun, act: CaseRun, ctx: CompareCtx) -> list[Mismatch]:
    out: list[Mismatch] = []
    for name in sorted(set(exp.files) | set(act.files)):
        e, a = exp.files.get(name), act.files.get(name)
        if e is not None and a is not None:
            e, a = _norm(e, ctx.normalisers), _norm(a, ctx.normalisers)
        if e == a:
            continue
        if a is None:
            out.append(Mismatch("FILE_MISSING", f"file {name}", f"FILE_MISSING file:{name}",
                                [FieldDiff(location=f"file {name}", expected="present", actual="missing")]))
            continue
        if e is None:
            out.append(Mismatch("FILE_EXTRA", f"file {name}", f"FILE_EXTRA file:{name}",
                                [FieldDiff(location=f"file {name}", expected="absent", actual="created")]))
            continue
        fc = ctx.output_files.get(name)
        if fc is None or fc.fd is None or not fc.fd.records:
            k = next((i for i in range(min(len(e), len(a))) if e[i] != a[i]), min(len(e), len(a)))
            out.append(Mismatch("FILE_CONTENT", f"file {name} byte {k}", f"FILE_CONTENT file:{name}",
                                [FieldDiff(location=f"file {name} from byte {k}", expected=_show(e[k:k + 60]), actual=_show(a[k:k + 60]))]))
            continue
        er, ar = _records(e, fc), _records(a, fc)
        r = next((i for i in range(min(len(er), len(ar))) if er[i] != ar[i]), None)
        if r is None:
            out.append(Mismatch("RECORD_COUNT", f"file {name}", f"RECORD_COUNT file:{name}",
                                [FieldDiff(location=f"file {name} record count", expected=str(len(er)), actual=str(len(ar)))]))
            continue
        rec = fc.fd.records[0]
        loc = f"file {name} record {r + 1}"
        diffs, items = [], []
        for (item, ev), (_i2, av) in zip(decode_record(rec, er[r]), decode_record(rec, ar[r]), strict=False):
            if ev != av:
                diffs.append(FieldDiff(location=loc, field=item.name, pic=item.pic_text(), expected=ev, actual=av))
                items.append(item)
        if not diffs:
            diffs.append(FieldDiff(location=loc, expected=_show(er[r]), actual=_show(ar[r])))
        sig = f"VALUE_MISMATCH file:{name}:{items[0].name}" if items else f"FILE_CONTENT file:{name}"
        out.append(Mismatch("VALUE_MISMATCH" if items else "FILE_CONTENT", loc, sig, diffs, items))
    return out


def numeric_view(item: DataItem | None, shown: str) -> str:
    return display_value(item, shown) if item is not None else shown
