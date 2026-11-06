       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOANCALC.
      *----------------------------------------------------------------
      * Equal-principal loan schedules.  stdin: groups of three lines
      * (principal PIC 9(6)V99, annual rate % PIC 9(2)V99, term in
      * months PIC 9(3)) repeated until a principal of zero (or end of
      * input, which ACCEPTs as zero) or 20 loans.
      * Targets: ACCEPT loop until a sentinel, ACCEPT window truncation
      * of decimal fields, PERFORM VARYING up to 360 iterations,
      * ROUNDED intermediate results stored in a V9(6) field vs. one
      * multi-division COMPUTE (intermediate precision), unsigned
      * targets dropping the sign, ADD with silent high-order
      * truncation, ON SIZE ERROR / NOT ON SIZE ERROR, RETURN-CODE 4.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PRINCIPAL          PIC 9(6)V99.
       01 WS-RATE               PIC 9(2)V99.
       01 WS-TERM               PIC 9(3).
          88 TERM-VALID         VALUE 1 THRU 360.
       01 WS-LOAN-NO            PIC 9(2) VALUE 0.
       01 WS-DONE               PIC X VALUE "N".
          88 NO-MORE-LOANS      VALUE "Y".
       01 WS-BALANCE            PIC S9(6)V99.
       01 WS-MONTHLY-RATE       PIC V9(6).
       01 WS-INTEREST           PIC 9(5)V99.
       01 WS-PRIN-PART          PIC 9(6)V99.
       01 WS-PAYMENT            PIC 9(6)V99.
       01 WS-TOTAL-INT          PIC 9(7)V99.
       01 WS-ESTIMATE           PIC 9(7)V99.
       01 WS-EST-FLAG           PIC X(4).
       01 WS-MONTH              PIC 9(3).
       01 WS-MAX-PAY            PIC 9(4)V99.
       01 WS-PAY-FLAG           PIC X(4).
       01 WS-GRAND-PRIN         PIC 9(8)V99 VALUE 0.
       01 WS-GRAND-INT          PIC 9(8)V99 VALUE 0.
       01 WS-SKIPPED            PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM READ-REQUEST
           PERFORM UNTIL NO-MORE-LOANS
               IF TERM-VALID
                   PERFORM AMORTIZE
                   PERFORM SHOW-LOAN
               ELSE
                   DISPLAY "LOAN " WS-LOAN-NO " REJECTED: TERM "
                           WS-TERM
                   ADD 1 TO WS-SKIPPED
               END-IF
               PERFORM READ-REQUEST
           END-PERFORM
           DISPLAY "LOANS " WS-LOAN-NO " SKIPPED " WS-SKIPPED
           DISPLAY "TOTAL PRINCIPAL " WS-GRAND-PRIN
                   " TOTAL INTEREST " WS-GRAND-INT
           IF WS-SKIPPED > 0
               MOVE 4 TO RETURN-CODE
           END-IF
           STOP RUN.
       READ-REQUEST.
           ACCEPT WS-PRINCIPAL
           IF WS-PRINCIPAL = 0 OR WS-LOAN-NO NOT < 20
               MOVE "Y" TO WS-DONE
           ELSE
               ACCEPT WS-RATE
               ACCEPT WS-TERM
               ADD 1 TO WS-LOAN-NO
           END-IF.
       AMORTIZE.
           MOVE WS-PRINCIPAL TO WS-BALANCE
           COMPUTE WS-MONTHLY-RATE ROUNDED = WS-RATE / 1200
           COMPUTE WS-PRIN-PART ROUNDED = WS-PRINCIPAL / WS-TERM
           MOVE 0 TO WS-TOTAL-INT WS-MAX-PAY
           MOVE "OK" TO WS-PAY-FLAG
           COMPUTE WS-ESTIMATE ROUNDED =
                   WS-PRINCIPAL * WS-RATE / 1200 * (WS-TERM + 1) / 2
               ON SIZE ERROR
                   MOVE 0 TO WS-ESTIMATE
                   MOVE "OVF" TO WS-EST-FLAG
               NOT ON SIZE ERROR
                   MOVE "OK" TO WS-EST-FLAG
           END-COMPUTE
           PERFORM VARYING WS-MONTH FROM 1 BY 1
                   UNTIL WS-MONTH > WS-TERM
               COMPUTE WS-INTEREST ROUNDED =
                       WS-BALANCE * WS-MONTHLY-RATE
               IF WS-MONTH = WS-TERM
                   MOVE WS-BALANCE TO WS-PRIN-PART
               END-IF
               COMPUTE WS-PAYMENT = WS-PRIN-PART + WS-INTEREST
               SUBTRACT WS-PRIN-PART FROM WS-BALANCE
               ADD WS-INTEREST TO WS-TOTAL-INT
               IF WS-PAYMENT > WS-MAX-PAY
                   COMPUTE WS-MAX-PAY = WS-PAYMENT
                       ON SIZE ERROR
                           MOVE "HIGH" TO WS-PAY-FLAG
                   END-COMPUTE
               END-IF
           END-PERFORM
           ADD WS-PRINCIPAL TO WS-GRAND-PRIN
           ADD WS-TOTAL-INT TO WS-GRAND-INT.
       SHOW-LOAN.
           DISPLAY "LOAN " WS-LOAN-NO " PRINCIPAL " WS-PRINCIPAL
                   " RATE " WS-RATE " TERM " WS-TERM
           DISPLAY "  MONTHLY RATE " WS-MONTHLY-RATE
                   " PRINCIPAL PART " WS-PRIN-PART
                   " FINAL BALANCE " WS-BALANCE
           DISPLAY "  INTEREST " WS-TOTAL-INT " ESTIMATE " WS-ESTIMATE
                   " " WS-EST-FLAG " MAX PAYMENT " WS-MAX-PAY " "
                   WS-PAY-FLAG.
