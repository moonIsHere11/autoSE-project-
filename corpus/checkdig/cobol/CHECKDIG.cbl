       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHECKDIG.
      *----------------------------------------------------------------
      * Validates up to three 10-character account numbers (one per
      * stdin line).  Positions 1-9 are the body, position 10 is the
      * check digit.  Mod-11 check digit with weights 10 down to 2:
      *   remainder 0 -> check 0, remainder 1 -> no valid check
      *   digit ("X"), otherwise check = 11 - remainder.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ACCOUNT          PIC X(10).
       01 WS-ACCT-NO          PIC 9(1)  VALUE 0.
       01 WS-VALID-COUNT      PIC 9(1)  VALUE 0.
       01 WS-I                PIC 9(2).
       01 WS-WEIGHT           PIC 9(2).
       01 WS-DIGIT            PIC 9(1).
       01 WS-GIVEN            PIC 9(1).
       01 WS-SUM              PIC 9(3).
       01 WS-QUOT             PIC 9(3).
       01 WS-REM              PIC 9(2).
       01 WS-CHECK            PIC 9(2).
       01 WS-CHECK-D          PIC 9(1).
       01 WS-CHECK-X          PIC X(1).
       01 WS-BAD              PIC 9(2).
       01 WS-RESULT           PIC X(7).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CHECK-ONE 3 TIMES
           DISPLAY "VALID ACCOUNTS: " WS-VALID-COUNT
           STOP RUN.
       CHECK-ONE.
           ADD 1 TO WS-ACCT-NO
           ACCEPT WS-ACCOUNT
           PERFORM SCAN-CHARS
           IF WS-BAD > 0
               DISPLAY WS-ACCT-NO " [" WS-ACCOUNT "] REJECTED: "
                       WS-BAD " NON-DIGIT(S)"
           ELSE
               PERFORM WEIGH-DIGITS
               PERFORM DERIVE-CHECK
               PERFORM REPORT-RESULT
           END-IF.
       SCAN-CHARS.
           MOVE 0 TO WS-BAD
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
               IF WS-ACCOUNT (WS-I:1) IS NOT NUMERIC
                   ADD 1 TO WS-BAD
               END-IF
           END-PERFORM.
       WEIGH-DIGITS.
           MOVE 0 TO WS-SUM
           PERFORM VARYING WS-WEIGHT FROM 10 BY -1 UNTIL WS-WEIGHT < 2
               COMPUTE WS-I = 11 - WS-WEIGHT
               MOVE WS-ACCOUNT (WS-I:1) TO WS-DIGIT
               COMPUTE WS-SUM = WS-SUM + WS-DIGIT * WS-WEIGHT
           END-PERFORM.
       DERIVE-CHECK.
           DIVIDE WS-SUM BY 11 GIVING WS-QUOT REMAINDER WS-REM
           EVALUATE WS-REM
               WHEN 0
                   MOVE 0 TO WS-CHECK
               WHEN 1
                   MOVE 10 TO WS-CHECK
               WHEN OTHER
                   COMPUTE WS-CHECK = 11 - WS-REM
           END-EVALUATE.
       REPORT-RESULT.
           MOVE WS-ACCOUNT (10:1) TO WS-GIVEN
           IF WS-CHECK = 10
               MOVE "X" TO WS-CHECK-X
               MOVE "NOCHECK" TO WS-RESULT
           ELSE
               MOVE WS-CHECK TO WS-CHECK-D
               MOVE WS-CHECK-D TO WS-CHECK-X
               IF WS-CHECK-D = WS-GIVEN
                   MOVE "VALID" TO WS-RESULT
                   ADD 1 TO WS-VALID-COUNT
               ELSE
                   MOVE "INVALID" TO WS-RESULT
               END-IF
           END-IF
           DISPLAY WS-ACCT-NO " " WS-ACCOUNT " " WS-RESULT
                   " CHECK=" WS-CHECK-X " SUM=" WS-SUM
                   " Q=" WS-QUOT " R=" WS-REM.
