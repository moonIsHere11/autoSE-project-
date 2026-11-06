       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIGITS.
      *----------------------------------------------------------------
      * Digit arithmetic.  stdin: numbers PIC 9(6), one per line, until
      * 0 (also end of input) or 15 numbers.  For each number: digit
      * sum, digital root, 6-digit reversal / palindrome test, Luhn
      * check, classification and division by 7.
      * Targets: REDEFINES of an ACCEPTed number as a digit table
      * (OCCURS), PERFORM VARYING upwards and downwards (BY -1),
      * PERFORM n TIMES, PERFORM UNTIL, DIVIDE ... GIVING ... REMAINDER
      * in loops, PERFORM ... THRU over a range whose paragraphs fall
      * through into each other, fall-through from MAIN-PARA into
      * SUMMARY-PARA, 88-levels, EVALUATE TRUE, ROUNDED vs truncation,
      * ACCEPT loop until a sentinel, RETURN-CODE = Luhn-valid count.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM                PIC 9(6).
       01 WS-NUM-DIGITS REDEFINES WS-NUM.
          05 WS-DIGIT           PIC 9 OCCURS 6 TIMES.
       01 WS-COUNT              PIC 9(2) VALUE 0.
       01 WS-I                  PIC 9.
       01 WS-POS                PIC 9.
       01 WS-Q                  PIC 9(6).
       01 WS-REM                PIC 9.
       01 WS-SUM                PIC 9(2).
       01 WS-ROOT               PIC 9(2).
       01 WS-EVEN-COUNT         PIC 9.
       01 WS-MAX-DIGIT          PIC 9.
       01 WS-WORK               PIC 9(6).
       01 WS-REV                PIC 9(6).
       01 WS-PALIN              PIC X(3).
          88 IS-PALINDROME      VALUE "YES".
       01 WS-LUHN-SUM           PIC 9(3).
       01 WS-DBL                PIC 9(2).
       01 WS-LUHN-OK            PIC X.
          88 LUHN-VALID         VALUE "Y".
       01 WS-KIND               PIC X(10).
       01 WS-SEVENTH            PIC 9(5)V99.
       01 WS-SEVENTH-T          PIC 9(5)V99.
       01 WS-GRAND              PIC 9(7) VALUE 0.
       01 WS-LUHN-COUNT         PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM READ-NUMBER
           PERFORM PROCESS-NUMBER THRU PROCESS-EXIT
               UNTIL WS-NUM = 0 OR WS-COUNT > 15.
       SUMMARY-PARA.
           DISPLAY "NUMBERS " WS-COUNT " GRAND " WS-GRAND
                   " LUHN-VALID " WS-LUHN-COUNT
           MOVE WS-LUHN-COUNT TO RETURN-CODE
           STOP RUN.
       PROCESS-NUMBER.
           MOVE 0 TO WS-SUM WS-EVEN-COUNT WS-MAX-DIGIT
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 6
               ADD WS-DIGIT (WS-I) TO WS-SUM
               DIVIDE WS-DIGIT (WS-I) BY 2 GIVING WS-Q REMAINDER WS-REM
               IF WS-REM = 0
                   ADD 1 TO WS-EVEN-COUNT
               END-IF
               IF WS-DIGIT (WS-I) > WS-MAX-DIGIT
                   MOVE WS-DIGIT (WS-I) TO WS-MAX-DIGIT
               END-IF
           END-PERFORM.
       DIGITAL-ROOT.
           MOVE WS-SUM TO WS-ROOT
           PERFORM UNTIL WS-ROOT < 10
               DIVIDE WS-ROOT BY 10 GIVING WS-Q REMAINDER WS-REM
               COMPUTE WS-ROOT = WS-Q + WS-REM
           END-PERFORM.
       REVERSE-NUMBER.
           MOVE WS-NUM TO WS-WORK
           MOVE 0 TO WS-REV
           PERFORM 6 TIMES
               DIVIDE WS-WORK BY 10 GIVING WS-Q REMAINDER WS-REM
               MOVE WS-Q TO WS-WORK
               COMPUTE WS-REV = WS-REV * 10 + WS-REM
           END-PERFORM
           IF WS-REV = WS-NUM
               MOVE "YES" TO WS-PALIN
           ELSE
               MOVE "NO" TO WS-PALIN
           END-IF.
       LUHN-CHECK.
           MOVE 0 TO WS-LUHN-SUM
           PERFORM VARYING WS-I FROM 6 BY -1 UNTIL WS-I < 1
               COMPUTE WS-POS = 7 - WS-I
               DIVIDE WS-POS BY 2 GIVING WS-Q REMAINDER WS-REM
               IF WS-REM = 0
                   COMPUTE WS-DBL = WS-DIGIT (WS-I) * 2
                   IF WS-DBL > 9
                       SUBTRACT 9 FROM WS-DBL
                   END-IF
                   ADD WS-DBL TO WS-LUHN-SUM
               ELSE
                   ADD WS-DIGIT (WS-I) TO WS-LUHN-SUM
               END-IF
           END-PERFORM
           DIVIDE WS-LUHN-SUM BY 10 GIVING WS-Q REMAINDER WS-REM
           IF WS-REM = 0
               MOVE "Y" TO WS-LUHN-OK
           ELSE
               MOVE "N" TO WS-LUHN-OK
           END-IF.
       CLASSIFY.
           EVALUATE TRUE
               WHEN WS-NUM < 10
                   MOVE "SINGLE" TO WS-KIND
               WHEN IS-PALINDROME
                   MOVE "PALINDROME" TO WS-KIND
               WHEN WS-EVEN-COUNT = 6
                   MOVE "ALL-EVEN" TO WS-KIND
               WHEN WS-ROOT = 9
                   MOVE "NINES" TO WS-KIND
               WHEN OTHER
                   MOVE "PLAIN" TO WS-KIND
           END-EVALUATE
           COMPUTE WS-SEVENTH ROUNDED = WS-NUM / 7
           COMPUTE WS-SEVENTH-T = WS-NUM / 7.
       PROCESS-EXIT.
           PERFORM SHOW-NUMBER
           ADD WS-NUM TO WS-GRAND
           IF LUHN-VALID
               ADD 1 TO WS-LUHN-COUNT
           END-IF
           PERFORM READ-NUMBER.
       SHOW-NUMBER.
           DISPLAY WS-COUNT " " WS-NUM " SUM " WS-SUM " ROOT " WS-ROOT
                   " EVEN " WS-EVEN-COUNT " MAX " WS-MAX-DIGIT
           DISPLAY "   REV " WS-REV " PALIN " WS-PALIN " LUHN "
                   WS-LUHN-SUM " " WS-LUHN-OK " " WS-KIND
                   " /7 " WS-SEVENTH " " WS-SEVENTH-T.
       READ-NUMBER.
           ACCEPT WS-NUM
           IF WS-NUM NOT = 0
               ADD 1 TO WS-COUNT
           END-IF.
