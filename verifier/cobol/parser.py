"""Parser for preprocessed COBOL (`cobc -E` output) into `syntax.Program`s.

Hand-written recursive descent (decision from spike S5). The DATA DIVISION is parsed fully; the
PROCEDURE DIVISION is parsed into generic statements with branches (IF/ELSE, EVALUATE/WHEN, inline
PERFORM bodies, ON SIZE ERROR / AT END / INVALID KEY / ... phrases). Anything not understood is
recorded in `Program.parse_errors` — never guessed.
"""

from __future__ import annotations

from verifier.cobol.datadiv import DataDivisionError, build_tree, parse_entries
from verifier.cobol.lexer import NUM, PERIOD, STR, WORD, Token
from verifier.cobol.syntax import Branch, FileControl, FileDescription, Paragraph, Program, Statement

VERBS = frozenset(
    """ACCEPT ADD ALLOCATE ALTER CALL CANCEL CLOSE COMMIT COMPUTE CONTINUE DELETE DISPLAY DIVIDE
    ENTRY EVALUATE EXEC EXHIBIT EXIT FREE GENERATE GO GOBACK IF INITIALIZE INITIATE INSPECT INVOKE
    MERGE MOVE MULTIPLY NEXT OPEN PERFORM RAISE READ RELEASE RESUME RETURN REWRITE ROLLBACK SEARCH
    SET SORT START STOP STRING SUBTRACT SUPPRESS TERMINATE TRANSFORM UNLOCK UNSTRING VALIDATE WRITE
    """.split()
)

ARITH = frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"})

# phrase name -> word sequences that introduce it (longest first)
PHRASES: dict[str, list[tuple[str, ...]]] = {
    "not_size_error": [("NOT", "ON", "SIZE", "ERROR"), ("NOT", "SIZE", "ERROR")],
    "size_error": [("ON", "SIZE", "ERROR"), ("SIZE", "ERROR")],
    "not_at_end": [("NOT", "AT", "END"), ("NOT", "END")],
    "at_end": [("AT", "END"), ("END",)],
    "not_invalid_key": [("NOT", "INVALID", "KEY"), ("NOT", "INVALID")],
    "invalid_key": [("INVALID", "KEY"), ("INVALID",)],
    "not_exception": [("NOT", "ON", "EXCEPTION"), ("NOT", "EXCEPTION")],
    "exception": [("ON", "EXCEPTION"), ("EXCEPTION",)],
    "not_overflow": [("NOT", "ON", "OVERFLOW"), ("NOT", "OVERFLOW")],
    "overflow": [("ON", "OVERFLOW"), ("OVERFLOW",)],
    "not_eop": [("NOT", "AT", "END-OF-PAGE"), ("NOT", "AT", "EOP"), ("NOT", "END-OF-PAGE"), ("NOT", "EOP")],
    "eop": [("AT", "END-OF-PAGE"), ("AT", "EOP"), ("END-OF-PAGE",), ("EOP",)],
}

VERB_PHRASES: dict[str, set[str]] = {
    **{v: {"size_error", "not_size_error"} for v in ARITH},
    "READ": {"at_end", "not_at_end", "invalid_key", "not_invalid_key"},
    "RETURN": {"at_end", "not_at_end"},
    "WRITE": {"eop", "not_eop", "invalid_key", "not_invalid_key"},
    "REWRITE": {"invalid_key", "not_invalid_key"},
    "DELETE": {"invalid_key", "not_invalid_key"},
    "START": {"invalid_key", "not_invalid_key"},
    "CALL": {"exception", "not_exception", "overflow", "not_overflow"},
    "STRING": {"overflow", "not_overflow"},
    "UNSTRING": {"overflow", "not_overflow"},
    "ACCEPT": {"exception", "not_exception"},
    "DISPLAY": {"exception", "not_exception"},
    "SEARCH": {"at_end"},
}

PHRASE_STARTS = frozenset({"NOT", "ON", "SIZE", "AT", "END", "INVALID", "EXCEPTION", "OVERFLOW", "END-OF-PAGE", "EOP"})

# Explicit scope terminators. User-defined names may also start with "END-" (e.g. a condition-name
# END-OF-FILE), so a prefix test is not enough.
SCOPE_TERMINATORS = frozenset(
    """END-ACCEPT END-ADD END-CALL END-CHAIN END-COMPUTE END-DELETE END-DISPLAY END-DIVIDE
    END-EVALUATE END-EXEC END-IF END-INVOKE END-JSON END-MULTIPLY END-PERFORM END-READ END-RECEIVE
    END-RETURN END-REWRITE END-SEARCH END-START END-STRING END-SUBTRACT END-UNSTRING END-WRITE
    END-XML""".split()
)

_SELECT_CLAUSES = frozenset({"ORGANIZATION", "ACCESS", "FILE", "STATUS", "LINE", "RECORD", "SEQUENTIAL",
                             "RESERVE", "PADDING", "LOCK", "SHARING", "ALTERNATE", "RELATIVE", "INDEXED"})


class ParseError(ValueError):
    pass


class _Cursor:
    def __init__(self, toks: list[Token]) -> None:
        self.toks = toks
        self.pos = 0

    def peek(self, k: int = 0) -> Token | None:
        i = self.pos + k
        return self.toks[i] if 0 <= i < len(self.toks) else None

    def next(self) -> Token:
        if self.pos >= len(self.toks):
            raise ParseError("unexpected end of source")
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def at_word(self, *words: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t is not None and t.is_word(*words)

    def at_seq(self, seq: tuple[str, ...]) -> bool:
        return all(self.at_word(w, k=i) for i, w in enumerate(seq))

    def eof(self) -> bool:
        return self.pos >= len(self.toks)

    def skip_to_period(self) -> list[Token]:
        out = []
        while not self.eof() and self.peek().kind != PERIOD:  # type: ignore[union-attr]
            out.append(self.next())
        if not self.eof():
            self.next()
        return out


def _phrase_at(cur: _Cursor) -> tuple[str, int] | None:
    t = cur.peek()
    if t is None or t.kind != WORD or t.up not in PHRASE_STARTS:
        return None
    for name, seqs in PHRASES.items():
        for seq in seqs:
            if cur.at_seq(seq):
                return name, len(seq)
    return None


# ---------------------------------------------------------------------------------------------
def split_programs(toks: list[Token]) -> list[list[Token]]:
    """Split a token stream at each IDENTIFICATION/ID DIVISION."""
    starts = [
        i
        for i, t in enumerate(toks)
        if t.is_word("IDENTIFICATION", "ID")
        and i + 1 < len(toks)
        and toks[i + 1].is_word("DIVISION")
    ]
    if not starts:
        raise ParseError("no IDENTIFICATION DIVISION found")
    chunks = []
    for a, b in zip(starts, [*starts[1:], len(toks)], strict=True):
        chunks.append(toks[a:b])
    return chunks


def parse_source(toks: list[Token], source_file: str) -> list[Program]:
    programs = []
    chunks = split_programs(toks)
    for idx, chunk in enumerate(chunks):
        prog = _ProgramParser(chunk, source_file).parse()
        if len(chunks) > 1 and idx > 0:
            prog.add_feature("multiple programs in one source", chunk[0].line)
        programs.append(prog)
    return programs


class _ProgramParser:
    def __init__(self, toks: list[Token], source_file: str) -> None:
        self.toks = toks
        self.source_file = source_file

    def _division_index(self, name: str) -> int | None:
        for i, t in enumerate(self.toks):
            if t.is_word(name) and i + 1 < len(self.toks) and self.toks[i + 1].is_word("DIVISION"):
                return i
        return None

    def parse(self) -> Program:
        toks = self.toks
        pid_idx = next((i for i, t in enumerate(toks) if t.is_word("PROGRAM-ID", "FUNCTION-ID")), None)
        if pid_idx is None:
            raise ParseError(f"{self.source_file}: no PROGRAM-ID")
        j = pid_idx + 1
        if j < len(toks) and toks[j].kind == PERIOD:
            j += 1
        name_tok = toks[j]
        pid = name_tok.value if name_tok.kind == STR else name_tok.text
        prog = Program(program_id=pid.upper(), source_file=self.source_file, line=toks[0].line)
        if toks[pid_idx].is_word("FUNCTION-ID"):
            prog.add_feature("user-defined FUNCTION", toks[pid_idx].line)
        env_i = self._division_index("ENVIRONMENT")
        data_i = self._division_index("DATA")
        proc_i = self._division_index("PROCEDURE")
        end_i = next(
            (i for i, t in enumerate(toks) if t.is_word("END") and i + 1 < len(toks) and toks[i + 1].is_word("PROGRAM", "FUNCTION")),
            len(toks),
        )
        bounds = sorted(x for x in (env_i, data_i, proc_i, end_i) if x is not None)

        def section_end(start: int) -> int:
            return next((b for b in bounds if b > start), len(toks))

        if env_i is not None:
            self._environment(prog, toks[env_i : section_end(env_i)])
        if data_i is not None:
            self._data(prog, toks[data_i : section_end(data_i)])
        for sel in prog.selects:
            if sel.assign_kind == "name" and prog.find_items(sel.assign or ""):
                sel.assign_kind = "dataname"  # ASSIGN TO <data item>: dynamic file name
            if sel.organization in ("INDEXED", "RELATIVE"):
                prog.add_feature(f"{sel.organization} file", sel.line)
        if proc_i is not None:
            _ProcedureParser(prog, toks[proc_i:end_i]).parse()
        return prog

    # ---- ENVIRONMENT DIVISION -----------------------------------------------------------------
    def _environment(self, prog: Program, toks: list[Token]) -> None:
        cur = _Cursor(toks)
        while not cur.eof():
            t = cur.next()
            if t.is_word("SELECT"):
                prog.selects.append(self._select(cur, t))
            elif t.is_word("DECIMAL-POINT"):
                prog.special_names.append("DECIMAL-POINT IS COMMA")
                prog.add_feature("DECIMAL-POINT IS COMMA", t.line)
            elif t.is_word("CURRENCY"):
                prog.special_names.append("CURRENCY SIGN")

    def _select(self, cur: _Cursor, sel_tok: Token) -> FileControl:
        optional = False
        if cur.at_word("OPTIONAL"):
            cur.next()
            optional = True
        name = cur.next().text.upper()
        assign, assign_kind = None, "none"
        org, access, status = "SEQUENTIAL", "SEQUENTIAL", None
        org_explicit = False
        line_seq = False
        while not cur.eof() and cur.peek().kind != PERIOD:  # type: ignore[union-attr]
            t = cur.next()
            w = t.up if t.kind == WORD else ""
            if w == "ASSIGN":
                if cur.at_word("TO", "USING"):
                    cur.next()
                while cur.at_word("EXTERNAL", "DYNAMIC", "DISK"):
                    cur.next()
                a = cur.peek()
                if a is not None and a.kind == STR:
                    cur.next()
                    assign, assign_kind = a.value, "literal"
                elif a is not None and a.is_word("KEYBOARD", "DISPLAY", "PRINTER"):
                    cur.next()
                    assign, assign_kind = a.up, "device"
                elif a is not None and a.kind == WORD and a.up not in _SELECT_CLAUSES:
                    cur.next()
                    assign, assign_kind = a.text, "name"
            elif w == "ORGANIZATION":
                if cur.at_word("IS"):
                    cur.next()
                org_explicit = True
                if cur.at_word("LINE"):
                    cur.next()
                    cur.next()  # SEQUENTIAL
                    org = "LINE SEQUENTIAL"
                elif cur.at_word("RECORD"):
                    cur.next()
                    cur.next()
                    org = "SEQUENTIAL"
                else:
                    org = cur.next().up
            elif w == "LINE" and cur.at_word("SEQUENTIAL") and not org_explicit:
                cur.next()
                org, line_seq = "LINE SEQUENTIAL", True
            elif w in ("SEQUENTIAL", "INDEXED", "RELATIVE") and not org_explicit and not line_seq:
                org = w
            elif w == "ACCESS":
                if cur.at_word("MODE"):
                    cur.next()
                if cur.at_word("IS"):
                    cur.next()
                access = cur.next().up
            elif w == "STATUS" or (w == "FILE" and cur.at_word("STATUS")):
                if w == "FILE":
                    cur.next()
                if cur.at_word("IS"):
                    cur.next()
                status = cur.next().text.upper()
        if not cur.eof():
            cur.next()
        return FileControl(name, assign, assign_kind, org, access, status, optional, sel_tok.line, sel_tok.file)

    # ---- DATA DIVISION --------------------------------------------------------------------------
    def _data(self, prog: Program, toks: list[Token]) -> None:
        cur = _Cursor(toks)
        cur.next()  # DATA
        cur.next()  # DIVISION
        if not cur.eof() and cur.peek().kind == PERIOD:  # type: ignore[union-attr]
            cur.next()
        section = ""
        buf: list[Token] = []
        fd: FileDescription | None = None

        def flush() -> None:
            nonlocal buf, fd
            if not buf:
                return
            try:
                entries = parse_entries(buf, section)
                roots = build_tree(entries)
            except (DataDivisionError, IndexError, ValueError) as exc:
                prog.parse_errors.append(f"DATA DIVISION ({section}): {exc}")
                buf = []
                return
            if section == "FILE" and fd is not None:
                for r in roots:
                    r.fd = fd.name
                    for it in r.walk():
                        it.fd = fd.name
                fd.records.extend(roots)
            elif section == "WORKING-STORAGE":
                prog.working_storage.extend(roots)
            elif section == "LOCAL-STORAGE":
                prog.local_storage.extend(roots)
            elif section == "LINKAGE":
                prog.linkage.extend(roots)
            buf = []

        while not cur.eof():
            t = cur.peek()
            assert t is not None
            if t.kind == WORD and cur.at_word("SECTION", k=1):
                flush()
                fd = None
                section = t.up
                if section in ("REPORT", "SCREEN", "COMMUNICATION"):
                    prog.add_feature(f"{section} SECTION", t.line)
                cur.next()
                cur.next()
                if not cur.eof() and cur.peek().kind == PERIOD:  # type: ignore[union-attr]
                    cur.next()
                continue
            if t.is_word("FD", "SD", "RD"):
                flush()
                kind = cur.next().up
                fname = cur.next().text.upper()
                header = cur.skip_to_period()
                fd = FileDescription(fname, kind, [], t.line,
                                     record_varying=any(h.is_word("VARYING") for h in header))
                if kind == "SD":
                    prog.add_feature("SORT/MERGE (SD)", t.line)
                if kind == "RD":
                    prog.add_feature("REPORT WRITER", t.line)
                prog.fds.append(fd)
                continue
            if t.is_word("COPY", "EXEC"):
                if t.is_word("EXEC"):
                    nxt = cur.peek(1)
                    prog.add_feature(f"EXEC {nxt.up if nxt is not None else ''}".strip(), t.line)
                while not cur.eof() and not cur.at_word("END-EXEC"):
                    cur.next()
                if not cur.eof():
                    cur.next()
                if not cur.eof() and cur.peek().kind == PERIOD:  # type: ignore[union-attr]
                    cur.next()
                continue
            # ordinary entry: copy tokens to the entry buffer
            buf.append(cur.next())
        flush()


# ---------------------------------------------------------------------------------------------
class _ProcedureParser:
    def __init__(self, prog: Program, toks: list[Token]) -> None:
        self.prog = prog
        self.cur = _Cursor(toks)
        self.procedure_names: set[str] = set()

    def _prescan_names(self) -> None:
        toks = self.cur.toks
        prev_kind = PERIOD
        for i, t in enumerate(toks):
            if prev_kind == PERIOD and t.kind == WORD and t.up not in VERBS and i + 1 < len(toks):
                nxt = toks[i + 1]
                if nxt.kind == PERIOD or nxt.is_word("SECTION"):
                    self.procedure_names.add(t.up)
            if t.kind == NUM and prev_kind == PERIOD and i + 1 < len(toks) and toks[i + 1].kind == PERIOD:
                self.procedure_names.add(t.up)  # numeric paragraph names
            prev_kind = t.kind

    def parse(self) -> None:
        cur = self.cur
        cur.next()  # PROCEDURE
        cur.next()  # DIVISION
        while not cur.eof() and cur.peek().kind != PERIOD:  # type: ignore[union-attr]
            hdr = cur.next()
            if hdr.is_word("USING"):
                while not cur.eof() and cur.peek().kind == WORD and not cur.at_word("RETURNING"):  # type: ignore[union-attr]
                    w = cur.next()
                    if w.up not in ("BY", "REFERENCE", "VALUE", "CONTENT"):
                        self.prog.using.append(w.up)
        if not cur.eof():
            cur.next()
        self._prescan_names()
        section: str | None = None
        para: Paragraph | None = None
        while not cur.eof():
            t = cur.peek()
            assert t is not None
            if t.is_word("DECLARATIVES"):
                self.prog.add_feature("DECLARATIVES", t.line)
                cur.next()
                cur.skip_to_period()
                continue
            if t.is_word("END") and cur.at_word("DECLARATIVES", k=1):
                cur.next()
                cur.next()
                cur.skip_to_period()
                continue
            if t.kind in (WORD, NUM) and t.up not in VERBS and cur.at_word("SECTION", k=1):
                section = t.up
                self.prog.sections.append(section)
                cur.next()
                cur.skip_to_period()
                para = None
                continue
            if t.kind in (WORD, NUM) and t.up not in VERBS and (cur.peek(1) is not None and cur.peek(1).kind == PERIOD):  # type: ignore[union-attr]
                if para is not None:
                    para.end_line = self._prev_line()
                cur.next()
                cur.next()
                para = Paragraph(t.up, section, t.file, t.line, t.line)
                self.prog.paragraphs.append(para)
                continue
            if t.kind == PERIOD:
                cur.next()
                continue
            # a sentence
            if para is None:
                para = Paragraph("(MAIN)" if section is None else section, section, t.file, t.line, t.line)
                self.prog.paragraphs.append(para)
            para.sentence_starts.append(len(para.statements))
            stmts = self._statements(frozenset())
            para.statements.extend(stmts)
            if not cur.eof() and cur.peek().kind == PERIOD:  # type: ignore[union-attr]
                cur.next()
            elif not stmts and not cur.eof():
                bad = cur.next()
                self.prog.parse_errors.append(f"{bad.file}:{bad.line}: unexpected {bad.text!r}")
        if para is not None:
            para.end_line = self._prev_line()

    def _prev_line(self) -> int:
        i = max(0, self.cur.pos - 1)
        return self.cur.toks[i].line if self.cur.toks else 0

    # ---- statements ----------------------------------------------------------------------------
    def _statements(self, stop: frozenset[str]) -> list[Statement]:
        cur = self.cur
        out: list[Statement] = []
        while not cur.eof():
            t = cur.peek()
            assert t is not None
            if t.kind == PERIOD:
                break
            if t.kind == WORD and t.up in stop:
                break
            if t.kind == WORD and t.up in PHRASE_STARTS and _phrase_at(cur) is not None:
                break  # a phrase of an enclosing statement
            if t.kind == WORD and t.up in VERBS:
                out.append(self._statement(stop))
                continue
            if t.kind == WORD and t.up in SCOPE_TERMINATORS:
                break  # terminator of an enclosing statement
            self.prog.parse_errors.append(f"{t.file}:{t.line}: unexpected {t.text!r} (expected a statement)")
            cur.next()
        return out

    def _statement(self, stop: frozenset[str]) -> Statement:
        verb_tok = self.cur.peek()
        assert verb_tok is not None
        verb = verb_tok.up
        if verb == "IF":
            return self._if(stop)
        if verb == "EVALUATE":
            return self._evaluate(stop)
        if verb == "PERFORM":
            return self._perform(stop)
        if verb == "SEARCH":
            return self._search(stop)
        if verb == "EXEC":
            return self._exec()
        return self._generic(stop)

    def _mk(self, verb_tok: Token, header: list[Token]) -> Statement:
        return Statement(verb_tok.up, header, verb_tok.file, verb_tok.line, header[-1].line if header else verb_tok.line)

    def _header_until(self, extra_stop: frozenset[str]) -> list[Token]:
        """Collect tokens until a verb, period, stop word or phrase introducer."""
        cur = self.cur
        out: list[Token] = []
        while not cur.eof():
            t = cur.peek()
            assert t is not None
            if t.kind == PERIOD:
                break
            if t.kind == WORD and (t.up in VERBS or t.up in extra_stop or t.up in SCOPE_TERMINATORS):
                break
            if t.kind == WORD and t.up in PHRASE_STARTS and _phrase_at(cur) is not None:
                break
            out.append(cur.next())
        return out

    def _generic(self, stop: frozenset[str]) -> Statement:
        cur = self.cur
        verb_tok = cur.next()
        verb = verb_tok.up
        header = [verb_tok]
        if verb == "GO":
            header += self._header_until(stop)
            self.prog.add_feature("GO TO", verb_tok.line)
        elif verb == "NEXT":
            if cur.at_word("SENTENCE"):
                header.append(cur.next())
        elif verb == "EXIT" and cur.at_word("PERFORM"):
            # EXIT PERFORM [CYCLE]: PERFORM is part of this statement, not a new one
            header.append(cur.next())
            if cur.at_word("CYCLE"):
                header.append(cur.next())
        else:
            header += self._header_until(stop | {"ELSE", "WHEN"})
        st = self._mk(verb_tok, header)
        own = VERB_PHRASES.get(verb, set())
        terminator = f"END-{verb}"
        while not cur.eof():
            ph = _phrase_at(cur)
            if ph is None or ph[0] not in own:
                break
            if ph[0] == "at_end" and cur.at_word("END") and verb not in ("READ", "RETURN", "SEARCH"):
                break
            name, n = ph
            ptoks = [cur.next() for _ in range(n)]
            phrase_stop = stop | {terminator} | {"ELSE", "WHEN"}
            body = self._statements(phrase_stop)
            st.branches.append(Branch(name, ptoks, body))
        if cur.at_word(terminator):
            cur.next()
            st.terminated = True
        st.end_line = self._prev_line()
        if verb in ("SORT", "MERGE", "RELEASE", "RETURN"):
            self.prog.add_feature("SORT/MERGE", verb_tok.line)
        if verb == "ALTER":
            self.prog.add_feature("ALTER", verb_tok.line)
        return st

    def _condition(self) -> list[Token]:
        """Condition tokens up to THEN / the first verb / NEXT SENTENCE."""
        cur = self.cur
        out: list[Token] = []
        while not cur.eof():
            t = cur.peek()
            assert t is not None
            if t.kind == PERIOD or (t.kind == WORD and (t.up in VERBS or t.up == "THEN" or t.up in SCOPE_TERMINATORS)):
                break
            out.append(cur.next())
        return out

    def _if(self, stop: frozenset[str]) -> Statement:
        cur = self.cur
        verb_tok = cur.next()
        cond = self._condition()
        st = self._mk(verb_tok, [verb_tok, *cond])
        if cur.at_word("THEN"):
            cur.next()
        then = self._statements(stop | {"ELSE", "END-IF"})
        st.branches.append(Branch("then", [], then))
        if cur.at_word("ELSE"):
            else_tok = cur.next()
            els = self._statements(stop | {"END-IF"})
            st.branches.append(Branch("else", [else_tok], els))
        if cur.at_word("END-IF"):
            cur.next()
            st.terminated = True
        st.end_line = self._prev_line()
        return st

    def _evaluate(self, stop: frozenset[str]) -> Statement:
        cur = self.cur
        verb_tok = cur.next()
        subjects: list[Token] = []
        while not cur.eof() and not cur.at_word("WHEN") and cur.peek().kind != PERIOD:  # type: ignore[union-attr]
            subjects.append(cur.next())
        st = self._mk(verb_tok, [verb_tok, *subjects])
        while cur.at_word("WHEN"):
            wtoks: list[Token] = []
            kind = "when"
            while cur.at_word("WHEN"):
                wtoks.append(cur.next())
                if cur.at_word("OTHER"):
                    wtoks.append(cur.next())
                    kind = "other"
                    break
                while not cur.eof():
                    t = cur.peek()
                    assert t is not None
                    if t.kind == PERIOD or (t.kind == WORD and (t.up in VERBS or t.up == "WHEN" or t.up in SCOPE_TERMINATORS)):
                        break
                    wtoks.append(cur.next())
            body = self._statements(stop | {"WHEN", "END-EVALUATE"})
            st.branches.append(Branch(kind, wtoks, body))
        if cur.at_word("END-EVALUATE"):
            cur.next()
            st.terminated = True
        st.end_line = self._prev_line()
        return st

    def _perform(self, stop: frozenset[str]) -> Statement:
        cur = self.cur
        verb_tok = cur.next()
        nxt = cur.peek()
        out_of_line = nxt is not None and nxt.kind in (WORD, NUM) and nxt.up in self.procedure_names and not cur.at_word("TIMES", k=1)
        if out_of_line:
            header = [verb_tok, *self._header_until(stop | {"ELSE", "WHEN"})]
            st = self._mk(verb_tok, header)
            if any(t.is_word("THRU", "THROUGH") for t in header):
                self.prog.add_feature("PERFORM THRU", verb_tok.line)
            st.end_line = self._prev_line()
            return st
        header = [verb_tok]
        while not cur.eof():
            t = cur.peek()
            assert t is not None
            if t.kind == PERIOD or (t.kind == WORD and (t.up in VERBS or t.up in SCOPE_TERMINATORS)):
                break
            header.append(cur.next())
        st = self._mk(verb_tok, header)
        body = self._statements(stop | {"END-PERFORM"})
        st.branches.append(Branch("body", [], body))
        if cur.at_word("END-PERFORM"):
            cur.next()
            st.terminated = True
        else:
            self.prog.parse_errors.append(f"{verb_tok.file}:{verb_tok.line}: inline PERFORM without END-PERFORM")
        st.end_line = self._prev_line()
        return st

    def _search(self, stop: frozenset[str]) -> Statement:
        cur = self.cur
        verb_tok = cur.next()
        header = [verb_tok, *self._header_until(stop | {"WHEN"})]
        st = self._mk(verb_tok, header)
        if cur.at_seq(("AT", "END")) or cur.at_word("END"):
            ptoks = [cur.next()]
            if ptoks[0].is_word("AT"):
                ptoks.append(cur.next())
            st.branches.append(Branch("at_end", ptoks, self._statements(stop | {"WHEN", "END-SEARCH"})))
        while cur.at_word("WHEN"):
            wtoks = [cur.next(), *self._condition()]
            st.branches.append(Branch("when", wtoks, self._statements(stop | {"WHEN", "END-SEARCH"})))
        if cur.at_word("END-SEARCH"):
            cur.next()
            st.terminated = True
        st.end_line = self._prev_line()
        return st

    def _exec(self) -> Statement:
        cur = self.cur
        verb_tok = cur.next()
        header = [verb_tok]
        nxt = cur.peek()
        kind = nxt.up if nxt is not None else ""
        while not cur.eof() and not cur.at_word("END-EXEC"):
            header.append(cur.next())
        if not cur.eof():
            header.append(cur.next())
        self.prog.add_feature(f"EXEC {kind}", verb_tok.line)
        st = self._mk(verb_tok, header)
        st.end_line = self._prev_line()
        return st
