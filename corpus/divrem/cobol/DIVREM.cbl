       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIVREM.
      *----------------------------------------------------------------
      * Integer and decimal division of two small numbers.
      * stdin line 1: dividend PIC S9(2) (canonical texts -9 .. 99);
      * line 2: divisor PIC 9.
      * T2a candidate: 109 x 10 = 1,090 canonical inputs.
      * Targets: DIVIDE ... GIVING ... REMAINDER (sign of the remainder
      * follows the dividend), DIVIDE ROUNDED with REMAINDER (the
      * remainder uses the truncated quotient), divide by zero with and
      * without ON SIZE ERROR, NOT ON SIZE ERROR, EVALUATE ... ALSO
      * with THRU and ANY, a loop (Euclid), RETURN-CODE 0 / 1 / 8.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DIVIDEND        PIC S9(2).
       01 WS-DIVISOR         PIC 9.
          88 DIVISOR-ZERO    VALUE 0.
          88 DIVISOR-SMALL   VALUE 1 THRU 3.
       01 WS-QUOT            PIC S9(2).
       01 WS-REM             PIC S9.
       01 WS-QUOT-R          PIC S9(2)V9.
       01 WS-REM-R           PIC S9V99.
       01 WS-RATIO           PIC S9V9 VALUE 0.
       01 WS-RATIO-FLAG      PIC X VALUE SPACE.
       01 WS-UQUOT           PIC 9(2) VALUE 77.
       01 WS-ACC             PIC S9(3) VALUE 120.
       01 WS-CHECK           PIC S9(3).
       01 WS-STATUS          PIC X(4).
       01 WS-KIND            PIC X(9).
       01 WS-DIV-CLASS       PIC X(8).
       01 WS-GCD-A           PIC 9(2).
       01 WS-GCD-B           PIC 9(2).
       01 WS-GCD-Q           PIC 9(2).
       01 WS-GCD-T           PIC 9(2).
       01 WS-STEPS           PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM GET-OPERANDS
           PERFORM DO-DIVIDE
           PERFORM CLASSIFY-RESULT
           PERFORM FIND-GCD
           PERFORM SHOW-RESULT
           PERFORM SET-RETURN
           STOP RUN.
       GET-OPERANDS.
           ACCEPT WS-DIVIDEND
           ACCEPT WS-DIVISOR.
       DO-DIVIDE.
           DIVIDE WS-DIVIDEND BY WS-DIVISOR
               GIVING WS-QUOT REMAINDER WS-REM
               ON SIZE ERROR
                   MOVE "ZDIV" TO WS-STATUS
               NOT ON SIZE ERROR
                   MOVE "OK" TO WS-STATUS
           END-DIVIDE
           DIVIDE WS-DIVIDEND BY WS-DIVISOR
               GIVING WS-QUOT-R ROUNDED REMAINDER WS-REM-R
               ON SIZE ERROR
                   CONTINUE
           END-DIVIDE
           DIVIDE WS-DIVIDEND BY WS-DIVISOR GIVING WS-RATIO ROUNDED
               ON SIZE ERROR
                   MOVE "Y" TO WS-RATIO-FLAG
               NOT ON SIZE ERROR
                   MOVE "N" TO WS-RATIO-FLAG
           END-DIVIDE
      *    no SIZE ERROR phrase: a zero divisor leaves the target as is
           DIVIDE WS-DIVISOR INTO WS-ACC
           DIVIDE WS-DIVIDEND BY WS-DIVISOR GIVING WS-UQUOT
           COMPUTE WS-CHECK = WS-QUOT * WS-DIVISOR + WS-REM.
       CLASSIFY-RESULT.
           EVALUATE TRUE ALSO TRUE
               WHEN DIVISOR-ZERO ALSO ANY
                   MOVE "UNDEFINED" TO WS-KIND
               WHEN WS-REM = 0 ALSO WS-DIVIDEND < 0
                   MOVE "NEG-EXACT" TO WS-KIND
               WHEN WS-REM = 0 ALSO ANY
                   MOVE "EXACT" TO WS-KIND
               WHEN WS-REM < 0 ALSO DIVISOR-SMALL
                   MOVE "NEG-SMALL" TO WS-KIND
               WHEN OTHER
                   MOVE "INEXACT" TO WS-KIND
           END-EVALUATE
           EVALUATE WS-DIVISOR ALSO WS-QUOT
               WHEN 0 ALSO ANY
                   MOVE "NONE" TO WS-DIV-CLASS
               WHEN 1 THRU 3 ALSO ANY
                   MOVE "LOW-DIV" TO WS-DIV-CLASS
               WHEN ANY ALSO 0
                   MOVE "ZERO-Q" TO WS-DIV-CLASS
               WHEN ANY ALSO -9 THRU -1
                   MOVE "NEG-Q" TO WS-DIV-CLASS
               WHEN OTHER
                   MOVE "HIGH-DIV" TO WS-DIV-CLASS
           END-EVALUATE.
       FIND-GCD.
           MOVE WS-DIVIDEND TO WS-GCD-A
           MOVE WS-DIVISOR TO WS-GCD-B
           PERFORM UNTIL WS-GCD-B = 0
               DIVIDE WS-GCD-A BY WS-GCD-B
                   GIVING WS-GCD-Q REMAINDER WS-GCD-T
               MOVE WS-GCD-B TO WS-GCD-A
               MOVE WS-GCD-T TO WS-GCD-B
               ADD 1 TO WS-STEPS
           END-PERFORM.
       SHOW-RESULT.
           DISPLAY "DIVIDEND " WS-DIVIDEND " DIVISOR " WS-DIVISOR
                   " STATUS " WS-STATUS
           DISPLAY "QUOT " WS-QUOT " REM " WS-REM " CHECK " WS-CHECK
           DISPLAY "QUOT-R " WS-QUOT-R " REM-R " WS-REM-R
           DISPLAY "RATIO " WS-RATIO " SIZE " WS-RATIO-FLAG
                   " UQUOT " WS-UQUOT " ACC " WS-ACC
           DISPLAY "KIND " WS-KIND " CLASS " WS-DIV-CLASS
                   " GCD " WS-GCD-A " STEPS " WS-STEPS.
       SET-RETURN.
           EVALUATE TRUE
               WHEN DIVISOR-ZERO
                   MOVE 8 TO RETURN-CODE
               WHEN WS-REM NOT = 0
                   MOVE 1 TO RETURN-CODE
               WHEN OTHER
                   MOVE 0 TO RETURN-CODE
           END-EVALUATE.
