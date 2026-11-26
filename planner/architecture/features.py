"""The "does similar work" signal, without an LLM: vocabulary (identifiers from the KB + comment words from a
simple comment-line scan) and I/O signature (stores touched, record layouts shared)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
from scipy import sparse

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



def _matrix(rows: list[dict], width: int) -> sparse.csr_matrix:
    r, c, v = [], [], []
    for i, row in enumerate(rows):
        for j, x in row.items():
            r.append(i)
            c.append(j)
            v.append(x)
    return sparse.csr_matrix((np.array(v, dtype=float), (r, c)), shape=(len(rows), max(width, 1)))


def similarity(kb: KnowledgeSource, cfg: PlannerConfig) -> dict[tuple[str, str], float]:
    """0.5 x cosine(TF-IDF of tokens) + 0.5 x jaccard(I/O signature), for pairs at or above the threshold.
    Computed for all pairs at once with sparse products (exactly the pairwise definition, without the
    quadratic Python loop)."""
    programs = sorted(kb.programs(), key=lambda p: p.id)
    n = len(programs)
    if n < 2:
        return {}
    root = kb.source_root()
    docs = [Counter(program_tokens(p, comment_lines(root / p.file))) for p in programs]
    df = Counter(t for counts in docs for t in counts)
    vocab: dict[str, int] = {}
    tfidf = []
    for counts in docs:
        total = sum(counts.values())
        tfidf.append({vocab.setdefault(t, len(vocab)): (c / total) * idf(n, df[t]) for t, c in counts.items()
                      if idf(n, df[t]) > 0})
    x = _matrix(tfidf, len(vocab))
    norms = np.sqrt(np.asarray(x.multiply(x).sum(axis=1)).ravel())
    x = sparse.diags(np.divide(1.0, norms, out=np.zeros_like(norms), where=norms > 0)) @ x
    cos = sparse.triu(x @ x.T, k=1).tocoo()

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
    items: dict = {}
    rows = [{items.setdefault(s, len(items)): 1.0 for s in sig[p.id]} for p in programs]
    b = _matrix(rows, len(items))
    sizes = np.asarray(b.sum(axis=1)).ravel()
    inter = sparse.triu(b @ b.T, k=1).tocoo()

    score: dict[tuple[int, int], float] = defaultdict(float)
    for i, j, v in zip(cos.row, cos.col, cos.data):
        score[(i, j)] += 0.5 * float(v)
    for i, j, v in zip(inter.row, inter.col, inter.data):
        union = sizes[i] + sizes[j] - v
        if union > 0:
            score[(i, j)] += 0.5 * float(v) / float(union)
    ids = [p.id for p in programs]
    return {(ids[i], ids[j]): s for (i, j), s in sorted(score.items())
            if s >= cfg.similarity_threshold and s > 0}


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
