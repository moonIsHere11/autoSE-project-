"""COBOL source loading: fixed/free format normalisation and COPY expansion.
Every produced line keeps its (file, line number) so spans point at real source."""
import re
from dataclasses import dataclass
from pathlib import Path

COBOL_EXTS = {".cbl", ".cob", ".cobol", ".pco", ".cpy", ".copy"}
COPY_EXTS = [".cpy", ".CPY", ".copy", ".cbl", ".CBL", ".cob", ".COB", ""]


@dataclass
class Line:
    file: str   # path relative to the source root
    no: int     # 1-based line number in that file
    text: str   # normalised code text (no sequence area, no comments)


def is_fixed(raw_lines):
    n = hit = 0
    for l in raw_lines[:200]:
        if len(l.strip()) < 8:
            continue
        n += 1
        if re.fullmatch(r"[0-9 ]{6}", l[:6]) and (len(l) < 7 or l[6] in " *-/DdC"):
            hit += 1
    return n > 0 and hit / n > 0.6


def load_file(path, rel):
    """-> (code lines, leading comment lines)."""
    raw = Path(path).read_text(errors="replace").expandtabs(8).splitlines()
    fixed = is_fixed(raw)
    out, header = [], []
    for i, l in enumerate(raw, 1):
        if fixed:
            ind = l[6] if len(l) > 6 else " "
            body = l[7:72] if len(l) > 7 else ""
            if ind in "*/":
                if not out and len(header) < 40:
                    header.append(l[7:].strip())
                continue
            if ind == "-" and out:  # continuation
                out[-1].text += body.strip().lstrip("'\"") if out[-1].text.count("'") % 2 else " " + body.strip()
                continue
            if ind in "Dd":
                continue
        else:
            s = l.strip()
            if s.startswith("*>"):
                if not out and len(header) < 40:
                    header.append(s[2:].strip())
                continue
            body = re.sub(r"\s\*>.*$", "", l)
        if body.strip():
            out.append(Line(rel, i, body.rstrip()))
    return out, header


class CopyResolver:
    def __init__(self, root):
        self.root = Path(root)
        self.index = {}
        for p in self.root.rglob("*"):
            if p.is_file() and p.suffix.lower() in COBOL_EXTS:
                self.index.setdefault(p.stem.upper(), p)
        self.unresolved = set()

    def find(self, name):
        return self.index.get(name.upper().strip("'\""))

    def expand(self, lines, depth=0, used=None):
        """Inline COPY statements. `used` collects copybook names."""
        used = used if used is not None else []
        out, i = [], 0
        while i < len(lines):
            ln = lines[i]
            m = re.match(r"\s*COPY\s+([A-Za-z0-9_'\"-]+)", ln.text, re.I)
            if not m:
                out.append(ln)
                i += 1
                continue
            stmt = ln.text
            j = i
            while not stmt.rstrip().endswith(".") and j + 1 < len(lines):
                j += 1
                stmt += " " + lines[j].text.strip()
            name = m.group(1).strip("'\"").upper()
            used.append(name)
            path = self.find(name)
            if path is None or depth > 5:
                self.unresolved.add(name)
                out.append(Line(ln.file, ln.no, "      *> unresolved COPY " + name))
            else:
                sub, _ = load_file(path, str(path.relative_to(self.root)))
                pairs = re.findall(r"==(.*?)==\s+BY\s+==(.*?)==", stmt, re.I | re.S)
                if pairs:
                    for s in sub:
                        for a, b in pairs:
                            s.text = re.sub(re.escape(a.strip()), b.strip(), s.text, flags=re.I)
                out.extend(self.expand(sub, depth + 1, used))
            i = j + 1
        return out
