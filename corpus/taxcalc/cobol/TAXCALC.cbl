       IDENTIFICATION DIVISION.
       PROGRAM-ID. TAXCALC.
      *----------------------------------------------------------------
      * Income tax for one filer.  stdin line 1: filing category
      * (PIC 9: 0 exempt, 1 single, 2 joint, 3 head of household,
      * 4-9 invalid); line 2: income in thousands (PIC 9(2)).
      * T2a candidate: 10 x 100 = 1,000 canonical inputs.
      * Targets: EVALUATE TRUE / EVALUATE ... THRU, 88-levels,
      * ROUNDED vs truncation, ON SIZE ERROR / NOT ON SIZE ERROR,
      * division by zero inside COMPUTE, unsigned target dropping the
      * sign, non-zero RETURN-CODE.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CATEGORY        PIC 9.
          88 CAT-EXEMPT      VALUE 0.
          88 CAT-SINGLE      VALUE 1.
          88 CAT-JOINT       VALUE 2.
          88 CAT-VALID       VALUE 0 THRU 3.
       01 WS-INCOME-K        PIC 9(2).
       01 WS-INCOME          PIC 9(6)V99.
       01 WS-DEDUCTION       PIC 9(5)V99.
       01 WS-TAXABLE         PIC S9(6)V99.
       01 WS-GAP             PIC 9(6)V99.
       01 WS-RATE            PIC V999.
       01 WS-BRACKET         PIC X(6).
       01 WS-TAX             PIC 9(5)V99.
       01 WS-TAX-TRUNC       PIC 9(5)V99.
       01 WS-SURCHARGE       PIC 9(3)V99 VALUE 0.
       01 WS-TOTAL-TAX       PIC 9(5)V99.
       01 WS-EFF-RATE        PIC 9(2)V99 VALUE 0.
       01 WS-SIZE-FLAG       PIC X VALUE "N".
          88 SURCHARGE-OVERFLOW VALUE "Y".
       01 WS-RATE-FLAG       PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM READ-INPUT
           IF CAT-VALID
               PERFORM COMPUTE-TAX
               PERFORM SHOW-RESULT
           ELSE
               DISPLAY "INVALID CATEGORY " WS-CATEGORY
               MOVE 4 TO RETURN-CODE
           END-IF
           STOP RUN.
       READ-INPUT.
           ACCEPT WS-CATEGORY
           ACCEPT WS-INCOME-K.
       COMPUTE-TAX.
           COMPUTE WS-INCOME = WS-INCOME-K * 1000
           EVALUATE TRUE
               WHEN CAT-EXEMPT
                   MOVE 99999.99 TO WS-DEDUCTION
               WHEN CAT-SINGLE
                   MOVE 12550 TO WS-DEDUCTION
               WHEN CAT-JOINT
                   MOVE 25100 TO WS-DEDUCTION
               WHEN OTHER
                   MOVE 18800.50 TO WS-DEDUCTION
           END-EVALUATE
           COMPUTE WS-TAXABLE = WS-INCOME - WS-DEDUCTION
      *    an unsigned target silently drops the sign
           COMPUTE WS-GAP = WS-INCOME - WS-DEDUCTION
           IF WS-TAXABLE < 0
               MOVE 0 TO WS-TAXABLE
           END-IF
           EVALUATE WS-INCOME-K
               WHEN 0 THRU 9
                   MOVE 0 TO WS-RATE
                   MOVE "NIL" TO WS-BRACKET
               WHEN 10 THRU 39
                   MOVE .1 TO WS-RATE
                   MOVE "LOW" TO WS-BRACKET
               WHEN 40 THRU 84
                   MOVE .225 TO WS-RATE
                   MOVE "MIDDLE" TO WS-BRACKET
               WHEN OTHER
                   MOVE .333 TO WS-RATE
                   MOVE "HIGH" TO WS-BRACKET
           END-EVALUATE
           COMPUTE WS-TAX ROUNDED = WS-TAXABLE * WS-RATE
           COMPUTE WS-TAX-TRUNC = WS-TAXABLE * WS-RATE
           COMPUTE WS-SURCHARGE ROUNDED = WS-TAX * 0.075
               ON SIZE ERROR
                   MOVE "Y" TO WS-SIZE-FLAG
               NOT ON SIZE ERROR
                   MOVE "N" TO WS-SIZE-FLAG
           END-COMPUTE
           ADD WS-TAX WS-SURCHARGE GIVING WS-TOTAL-TAX
           COMPUTE WS-EFF-RATE ROUNDED = WS-TOTAL-TAX * 100 / WS-INCOME
               ON SIZE ERROR
                   MOVE "Z" TO WS-RATE-FLAG
           END-COMPUTE
           IF SURCHARGE-OVERFLOW
               MOVE 2 TO RETURN-CODE
           END-IF.
       SHOW-RESULT.
           DISPLAY "CATEGORY " WS-CATEGORY " INCOME " WS-INCOME
                   " BRACKET " WS-BRACKET
           DISPLAY "DEDUCTION " WS-DEDUCTION " TAXABLE " WS-TAXABLE
                   " GAP " WS-GAP
           DISPLAY "TAX " WS-TAX " TRUNC " WS-TAX-TRUNC
                   " SURCHARGE " WS-SURCHARGE " OVERFLOW " WS-SIZE-FLAG
           DISPLAY "TOTAL " WS-TOTAL-TAX " EFFECTIVE " WS-EFF-RATE
                   "% FLAG " WS-RATE-FLAG.
