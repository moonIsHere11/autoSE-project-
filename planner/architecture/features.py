"""The "does similar work" signal, without an LLM: vocabulary (identifiers from the KB + comment words from a
simple comment-line scan) and I/O signature (stores touched, record layouts shared)."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx

from ..kb import KnowledgeSource, Program
from .config import PlannerConfig
from .graph import Evidence, idf

DROP = {"WS", "LK", "FILLER"}
STOPWORDS = {"THE", "AND", "FOR", "WITH", "FROM", "INTO", "THIS", "THAT", "ARE", "ALL", "ANY", "NOT", "WHEN"}
SPLIT = re.compile(r"[-_]")
WORD = re.compile(r"[A-Za-z0-9]+")


def comment_lines(path: Path) -> list[str]:
    """Comment text of a COBOL file: fixed-format lines with '*' or '/' in column 7, and free-format '*>' text."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        if len(line) > 6 and line[6] in "*/" and line[:6].strip(" 0123456789") == "":
            body = line[7:72].strip()
        elif "*>" in line:
            body = line.split("*>", 1)[1].strip()
        else:
            continue
        if body:
            out.append(body)
    return out


def _keep(tok: str) -> bool:
    return len(tok) >= 3 and not tok.isdigit() and tok not in DROP and tok not in STOPWORDS


def program_tokens(program: Program, comments: list[str]) -> list[str]:
    toks = [t.upper() for ident in program.identifiers for t in SPLIT.split(ident)]
    toks += [w.upper() for c in comments for w in WORD.findall(c)]
    return [t for t in toks if _keep(t)]


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def similarity(kb: KnowledgeSource, cfg: PlannerConfig) -> dict[tuple[str, str], float]:
    """0.5 x cosine(TF-IDF of tokens) + 0.5 x jaccard(I/O signature), for pairs at or above the threshold."""
    programs = kb.programs()
    n = len(programs)
    root = kb.source_root()
    docs = {p.id: Counter(program_tokens(p, comment_lines(root / p.file))) for p in programs}
    df = Counter(t for counts in docs.values() for t in counts)
    vec = {pid: {t: (c / sum(counts.values())) * idf(n, df[t]) for t, c in counts.items()}
           for pid, counts in docs.items() if counts}

    copy_users: dict[str, int] = Counter(c for p in programs for c in set(p.copybooks))
    records = {name for name, cb in kb.copybooks().items() if cb.kind == "record"}
    sig: dict[str, set] = defaultdict(set)
    for u in kb.store_uses():
        if u.store_kind != "private":
            sig[u.program].add(("store", u.store, u.mode))
    for p in programs:
        for c in p.copybooks:
            if c in records and idf(n, copy_users[c]) > 0:
                sig[p.id].add(("record", c))

    out = {}
    for a, b in combinations(sorted(p.id for p in programs), 2):
        s = 0.5 * _cosine(vec.get(a, {}), vec.get(b, {})) + 0.5 * _jaccard(sig[a], sig[b])
        if s >= cfg.similarity_threshold and s > 0:
            out[(a, b)] = s
    return out


def add_similarity(g: nx.Graph, sims: dict[tuple[str, str], float], cfg: PlannerConfig) -> None:
    for (a, b), s in sorted(sims.items()):
        weight = cfg.weights.similar * s
        if weight <= 0 or a == b:
            continue
        ev = Evidence("similar", "", f"{s:.2f}", weight)
        if g.has_edge(a, b):
            g.edges[a, b]["evidence"] = [e for e in g.edges[a, b]["evidence"] if e.kind != "similar"] + [ev]
            g.edges[a, b]["weight"] = sum(e.weight for e in g.edges[a, b]["evidence"])
        else:
            g.add_edge(a, b, weight=weight, evidence=[ev])
