      * ARITH - spike S5 sample 1: WORKING-STORAGE arithmetic.
      * Exercises COMPUTE ROUNDED, ADD ON SIZE ERROR, DIVIDE REMAINDER,
      * EVALUATE, PERFORM VARYING/TIMES/UNTIL, 88-levels, OCCURS,
      * REDEFINES, COMP-3, INITIALIZE, ACCEPT, DISPLAY.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COUNTERS.
           05  WS-I                PIC 9(3)      VALUE 0.
           05  WS-N                PIC 9(3)      VALUE 5.
       01  WS-AMOUNTS.
           05  WS-AMT              PIC S9(7)V99  COMP-3
                                   OCCURS 5 TIMES.
       01  WS-TOTAL                PIC S9(9)V99 USAGE COMP-3 VALUE ZERO.
       01  WS-AVG                  PIC S9(7)V99  VALUE ZEROS.
       01  WS-SMALL                PIC 9(3)      VALUE 990.
       01  WS-QUOT                 PIC 9(5).
       01  WS-REM                  PIC 9(3).
       01  WS-RATE                 PIC V999      VALUE .075.
       01  WS-TAX                  PIC S9(7)V99  COMP.
       01  WS-DATE                 PIC 9(8)      VALUE 20240229.
       01  WS-DATE-R REDEFINES WS-DATE.
           05  WS-YYYY             PIC 9(4).
           05  WS-MM               PIC 99.
           05  WS-DD               PIC 99.
       01  WS-GRADE                PIC X         VALUE SPACE.
           88  GRADE-A                           VALUE 'A'.
           88  GRADE-PASS                        VALUE 'A' 'B' 'C'.
           88  GRADE-FAIL                        VALUE 'D' THRU 'F'.
       01  WS-FLAGS.
           05  WS-OVERFLOW-SW      PIC X         VALUE 'N'.
               88  OVERFLOWED                    VALUE 'Y'.
           05  FILLER              PIC X(4)      VALUE ALL '*'.
       01  WS-OUT                  PIC -Z,ZZZ,ZZ9.99.
       01  WS-MSG                  PIC X(70)     VALUE 'IT''S A VERY LON
      -    'G MESSAGE LITERAL, CONTINUED ONTO THE NEXT LINE'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-N
           IF WS-N = ZERO OR WS-N > 5
               MOVE 5 TO WS-N
           END-IF
           INITIALIZE WS-AMOUNTS
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > WS-N
               COMPUTE WS-AMT (WS-I) ROUNDED =
                   WS-I * 1234.567 / 3 + 0.005
               ADD WS-AMT (WS-I) TO WS-TOTAL
                   ON SIZE ERROR MOVE 'Y' TO WS-OVERFLOW-SW
               END-ADD
           END-PERFORM
           DIVIDE WS-TOTAL BY WS-N GIVING WS-AVG ROUNDED
           DIVIDE 1000 BY 7 GIVING WS-QUOT REMAINDER WS-REM
           MULTIPLY WS-RATE BY WS-TOTAL GIVING WS-TAX ROUNDED
           SUBTRACT 10 FROM WS-SMALL
           ADD 20 TO WS-SMALL
               ON SIZE ERROR DISPLAY 'SIZE ERROR ON WS-SMALL'
               NOT ON SIZE ERROR DISPLAY 'NO SIZE ERROR'
           END-ADD
           PERFORM CLASSIFY-PARA
           PERFORM SHOW-PARA 2 TIMES
           MOVE WS-TOTAL TO WS-OUT
           DISPLAY 'TOTAL=' WS-OUT ' TAX=' WS-TAX
           DISPLAY 'Q=' WS-QUOT ', R=' WS-REM; DISPLAY WS-MSG
           IF WS-REM = ZERO DISPLAY 'EVEN'
           ELSE DISPLAY 'ODD'.
           IF OVERFLOWED
              DISPLAY "OVERFLOW" *> inline comment after code
           END-IF
           STOP RUN.
       CLASSIFY-PARA.
           EVALUATE TRUE
               WHEN WS-AVG > 1000
                   MOVE 'A' TO WS-GRADE
               WHEN WS-AVG > 500 AND WS-AVG NOT > 1000
                   MOVE 'B' TO WS-GRADE
               WHEN OTHER
                   MOVE 'E' TO WS-GRADE
           END-EVALUATE
           EVALUATE WS-MM
               WHEN 1 THRU 3   DISPLAY 'Q1'
               WHEN 4 THRU 6   DISPLAY 'Q2'
               WHEN OTHER      DISPLAY 'H2'
           END-EVALUATE
           IF GRADE-PASS
               DISPLAY 'PASS ' WS-GRADE
           ELSE
               IF GRADE-FAIL
                   DISPLAY 'FAIL ' WS-GRADE
               END-IF
           END-IF.
       SHOW-PARA.
           MOVE ZERO TO WS-I
           PERFORM UNTIL WS-I >= 2
               ADD 1 TO WS-I
               DISPLAY 'I=' WS-I ' AMT=' WS-AMT (WS-I)
           END-PERFORM.
