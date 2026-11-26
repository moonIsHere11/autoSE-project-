# Gold annotation guide (E6)

**Goal:** for every paragraph, write down which data items it reads and writes and where control goes. Phase 0 is scored against your files, so they must not share its blind spots.

**Ground rules**
- Work from the COBOL source only (`source` path in the template). **Never open `kb/`, Phase 0 output, Phase 1's `index.json` or this repo's eval results** before you hand in your file.
- Copy `TEMPLATE.json` to `gold/<your-initials>.json`, put your initials in `annotator`, fill every paragraph. Empty lists are valid answers.
- Both annotators do **LOANCALC** and **FALLTHRU** (overlap for agreement); split the other five.
- Order inside lists does not matter; no duplicates.

**Names.** A field is the path from its 01/77 item down to it, joined with `.`: `WS-PAY-WORK.WS-GROSS`, `EMP-REC.EMP-ID`, `WS-EOF`. Use elementary items only (items with a PIC). Never list `FILLER`. The special register is `RETURN-CODE`.

**reads** — every elementary item that appears in a reading position anywhere in the paragraph (ignore order inside the paragraph: if it is read anywhere, list it):
- sending operands of MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE expressions, DISPLAY operands;
- conditions of IF, EVALUATE (subjects and WHEN values), PERFORM UNTIL; an 88-level name reads its parent item;
- subscripts and reference-modification positions (`TBL-AMT (I)` reads `I`);
- `ADD A TO B`, `SUBTRACT A FROM B`, `MULTIPLY A BY B`, `DIVIDE A INTO B`: `B` is read **and** written (GIVING targets are only written);
- `PERFORM ... TIMES n` reads `n`; `PERFORM VARYING I FROM a BY b UNTIL c` reads `a`, `b`, the items in `c`, and `I` (and writes `I`);
- `WRITE rec` reads every elementary item of `rec`; `WRITE rec FROM x` reads `x` (and writes `rec`'s items).

**writes** — every elementary item some statement of the paragraph may store into (even if only on one branch): MOVE / arithmetic / COMPUTE targets, ACCEPT target, INITIALIZE operand, `SET cond TO TRUE` (writes the 88's parent), PERFORM VARYING control item, `READ f` (every elementary item of every record under `f`'s FD, plus the INTO target), and the FILE STATUS item named in the SELECT for OPEN / CLOSE / READ / WRITE.

**Groups, REDEFINES, partial writes**
- A group item in a read or write position stands for all its elementary items.
- An item shares storage with every item that REDEFINES it (or that it REDEFINES), at any level: a reference reads or writes every elementary item that shares at least one byte with it.
- A write that covers only part of an item also **reads** that item: a subscripted target (`MOVE 0 TO TBL-AMT (I)` reads and writes `TBL-AMT`), a reference-modified target (`MOVE 'X' TO NAME (1:1)`), or a write to an item that overlaps only part of another item.

**performs** — paragraphs or sections named by PERFORM in this paragraph (inline `PERFORM ... END-PERFORM` names nothing). For `PERFORM A THRU B` list every paragraph from A to B in source order. For a section, list the section name only.

**goes_to** — targets of GO TO (all names of `GO TO A B C DEPENDING ON X`).

**falls_through_to** — the next paragraph in source order (also across a SECTION header), unless the paragraph's **last** statement is STOP RUN, GOBACK, EXIT PROGRAM or a GO TO without DEPENDING. `null` for the last paragraph or when it always leaves. A GO TO or STOP RUN inside an IF does not stop fall-through.

**When unsure**, write your best answer and add a sibling key `"note": "..."` to that paragraph; notes are reported with the disagreements.
