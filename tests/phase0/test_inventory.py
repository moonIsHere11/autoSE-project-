from __future__ import annotations

from pathlib import Path

from phase0.stages.inventory import TextFile, call_refs, classify, inventory_entry, jcl_cards

REPO = Path(__file__).resolve().parents[2]

FIXED_PROG = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY CUSTREC.
       01 WS-PGM PIC X(8) VALUE 'SUBPGM'.
       PROCEDURE DIVISION.
           CALL 'LOGIT' USING WS-PGM
           CALL WS-PGM
           STOP RUN.
"""
COPYBOOK = """       01 CUST-REC.
          05 CUST-ID   PIC 9(5).
          05 CUST-NAME PIC X(20).
"""
JCL = """//PAYJOB   JOB (ACCT),'PAYROLL',CLASS=A
//*  comment card
//STEP01   EXEC PGM=PAYROLL
//INFILE   DD DSN=PAY.INPUT.DATA,DISP=SHR
//OUTFILE  DD DSN=PAY.OUTPUT.DATA,
//            DISP=(NEW,CATLG,DELETE)
//STEP02   EXEC PGM=REPORT
//INFILE   DD DSN=PAY.OUTPUT.DATA,DISP=SHR
"""


def entry(path: str, text: str) -> TextFile:
    return TextFile(path, text, text.encode("latin-1"))


def test_classify_by_content_not_extension() -> None:
    assert classify(FIXED_PROG, FIXED_PROG.encode())[0] == "program"
    assert classify(COPYBOOK, COPYBOOK.encode()) == ("copybook", "data")
    assert classify(JCL, JCL.encode()) == ("jcl", "job")
    assert classify("hello world\n", b"hello world\n") == ("other", None)
    assert classify("", b"") == ("other", "empty")
    assert classify("x", b"\0\1") == ("other", "binary")
    e = inventory_entry(entry("weird.txt", FIXED_PROG))
    assert e.kind == "program" and e.format == "fixed"


def test_references() -> None:
    e = inventory_entry(entry("p.cbl", FIXED_PROG))
    assert e.copybooks == ["CUSTREC"]
    assert e.calls == ["?WS-PGM", "LOGIT"]
    assert e.programs == ["DEMO"]
    assert call_refs("EXEC CICS XCTL PROGRAM('COSGN00C') END-EXEC") == ["COSGN00C"]
    assert call_refs("EXEC CICS LINK PROGRAM(WS-PGM) END-EXEC") == ["?WS-PGM"]


def test_comment_lines_are_ignored() -> None:
    text = FIXED_PROG.replace("           CALL 'LOGIT'", "      *    CALL 'LOGIT'")
    assert inventory_entry(entry("p.cbl", text)).calls == ["?WS-PGM"]


def test_jcl_steps_and_continuations() -> None:
    rows = jcl_cards(JCL)
    execs = [(r["step"], r["program"]) for r in rows if r["kind"] == "exec"]
    assert execs == [("STEP01", "PAYROLL"), ("STEP02", "REPORT")]
    out = next(r for r in rows if r["kind"] == "dd" and r["dd"] == "OUTFILE")
    assert out["dsn"] == "PAY.OUTPUT.DATA" and out["disp"] == "NEW,CATLG,DELETE"
    assert all(r["job"] == "PAYJOB" for r in rows)


def test_corpus_programs_classified() -> None:
    for p in sorted(REPO.glob("corpus/*/cobol/*.cbl")) + sorted(REPO.glob("tests/semantics/programs/*.cbl")):
        raw = p.read_bytes()
        assert classify(raw.decode("latin-1"), raw)[0] == "program", p


def test_prose_and_sql_declares_are_not_procedure_copybooks() -> None:
    md = "# Title\n\nIf you MOVE the files, PERFORM the steps below.\nDisplay the result.\n"
    assert classify(md, md.encode())[0] == "other"
    dcl = "      ******************\n           EXEC SQL DECLARE CARDDEMO.T TABLE\n           ( A CHAR(2) NOT NULL )\n           END-EXEC.\n"
    assert classify(dcl, dcl.encode()) == ("copybook", "sql")
    proc = "       9998-PRIMING-QUERY.\n           MOVE 1 TO WS-X\n           PERFORM 9999-EXIT.\n"
    assert classify(proc, proc.encode()) == ("copybook", "procedure")
