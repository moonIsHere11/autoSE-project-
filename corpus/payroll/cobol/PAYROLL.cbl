       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
      *----------------------------------------------------------------
      * Weekly payroll batch (the corpus' large program).
      * Input : EMPLOYEES.TXT  LINE SEQUENTIAL, 47-byte records.
      * Output: PAYSLIP.TXT    LINE SEQUENTIAL payslips with numeric-
      *                        edited amounts and a department summary
      *         PAYROLL.DAT    fixed-length SEQUENTIAL, 36-byte records
      *                        (COMP, COMP-3, overpunched zoned and
      *                        SIGN TRAILING SEPARATE fields)
      *         stdout         run totals; RETURN-CODE 4 on errors.
      * Employee types: H hourly (overtime x1.5 above 40 h, double
      * time above 60 h), S salaried (weekly salary), C commission
      * (base + sales x tier rate).  Tax codes A, B, C select a row of
      * the tax table, anything else the default row.
      * Targets: tables loaded by REDEFINES of FILLER VALUEs, OCCURS
      * with PERFORM VARYING (incl. a compound UNTIL), INITIALIZE,
      * EVALUATE TRUE ALSO TRUE, 88-levels, ROUNDED vs truncation,
      * intermediate precision in multi-term COMPUTEs, ON SIZE ERROR,
      * silent high-order truncation, numeric-edited output (Z, comma,
      * floating $, trailing -), IS NUMERIC validation.
      *----------------------------------------------------------------
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO "EMPLOYEES.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT SLIP-FILE ASSIGN TO "PAYSLIP.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT PAY-FILE ASSIGN TO "PAYROLL.DAT"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD EMP-FILE.
       01 EMP-REC.
          05 EMP-ID             PIC X(5).
          05 EMP-NAME           PIC X(15).
          05 EMP-DEPT           PIC 9.
             88 DEPT-VALID      VALUE 1 THRU 5.
          05 EMP-TYPE           PIC X.
             88 TYPE-HOURLY     VALUE "H".
             88 TYPE-SALARIED   VALUE "S".
             88 TYPE-COMMISSION VALUE "C".
             88 TYPE-VALID      VALUE "H" "S" "C".
          05 EMP-HOURS          PIC 9(3)V9.
          05 EMP-RATE           PIC 9(4)V99.
          05 EMP-SALES          PIC 9(6)V99.
          05 EMP-ALLOW          PIC S9(3)V99 SIGN LEADING SEPARATE.
          05 EMP-TAXCODE        PIC X.
       FD SLIP-FILE.
       01 SLIP-REC              PIC X(80).
       FD PAY-FILE.
       01 PAY-REC.
          05 PR-ID              PIC X(5).
          05 PR-DEPT            PIC 9.
          05 PR-TYPE            PIC X.
          05 PR-HOURS           PIC 9(3)V9 COMP.
          05 PR-OT-HOURS        PIC S9(3)V9.
          05 PR-GROSS           PIC S9(7)V99 COMP-3.
          05 PR-TAX             PIC S9(7)V99 COMP-3.
          05 PR-NET             PIC S9(7)V99 COMP-3.
          05 PR-ALLOW           PIC S9(3)V99 SIGN TRAILING SEPARATE.
          05 PR-SEQ             PIC 9(4) COMP.
       WORKING-STORAGE SECTION.
       01 WS-EOF                PIC X VALUE "N".
          88 END-OF-EMPLOYEES   VALUE "Y".
      * tax table: exemption 9(4)V99, rate V999 (rows A, B, C, other)
       01 WS-TAX-VALUES.
          05 FILLER             PIC X(9) VALUE "020000150".
          05 FILLER             PIC X(9) VALUE "030000200".
          05 FILLER             PIC X(9) VALUE "010000225".
          05 FILLER             PIC X(9) VALUE "000000300".
       01 WS-TAX-TABLE REDEFINES WS-TAX-VALUES.
          05 WS-TAX-ROW         OCCURS 4 TIMES.
             10 WS-TAX-EXEMPT   PIC 9(4)V99.
             10 WS-TAX-RATE     PIC V999.
      * commission tiers: sales limit 9(6)V99, rate V999
       01 WS-TIER-VALUES.
          05 FILLER             PIC X(11) VALUE "01000000020".
          05 FILLER             PIC X(11) VALUE "05000000035".
          05 FILLER             PIC X(11) VALUE "99999999050".
       01 WS-TIER-TABLE REDEFINES WS-TIER-VALUES.
          05 WS-TIER-ROW        OCCURS 3 TIMES.
             10 WS-TIER-LIMIT   PIC 9(6)V99.
             10 WS-TIER-RATE    PIC V999.
      * weekly health deduction per department 1-5
       01 WS-HEALTH-VALUES      PIC X(25)
                                VALUE "0250003000035500400000000".
       01 WS-HEALTH-TABLE REDEFINES WS-HEALTH-VALUES.
          05 WS-HEALTH-RATE     PIC 9(3)V99 OCCURS 5 TIMES.
       01 WS-PAY-WORK.
          05 WS-HOURS           PIC 9(3)V9.
          05 WS-RATE            PIC 9(4)V99.
          05 WS-SALES           PIC 9(6)V99.
          05 WS-ALLOW           PIC S9(3)V99.
          05 WS-REG-HOURS       PIC 9(3)V9.
          05 WS-OT-HOURS        PIC 9(3)V9.
          05 WS-DT-HOURS        PIC 9(3)V9.
          05 WS-COMMISSION      PIC 9(6)V99.
          05 WS-GROSS           PIC S9(7)V99.
          05 WS-TAXABLE         PIC S9(7)V99.
          05 WS-TAX             PIC S9(7)V99.
          05 WS-SURTAX          PIC S9(5)V99.
          05 WS-PENSION         PIC S9(5)V99.
          05 WS-HEALTH          PIC 9(3)V99.
          05 WS-NET             PIC S9(6)V99.
          05 WS-DEPT            PIC 9.
          05 WS-TAX-IDX         PIC 9.
          05 WS-TIER            PIC 9.
          05 WS-ERROR-MSG       PIC X(16).
       01 WS-DEPT-TOTALS.
          05 WS-DEPT-ROW        OCCURS 5 TIMES.
             10 DT-COUNT        PIC 9(3).
             10 DT-GROSS        PIC S9(9)V99.
             10 DT-NET          PIC S9(9)V99.
       01 WS-D                  PIC 9.
       01 WS-AVG-NET            PIC S9(7)V99.
       01 WS-READ-COUNT         PIC 9(3) VALUE 0.
       01 WS-PAID-COUNT         PIC 9(4) VALUE 0.
       01 WS-ERROR-COUNT        PIC 9(3) VALUE 0.
       01 WS-TOTAL-GROSS        PIC S9(9)V99 VALUE 0.
       01 WS-TOTAL-NET          PIC S9(9)V99 VALUE 0.
       01 WS-TOP-NET            PIC S9(6)V99 VALUE -999999.99.
       01 WS-TOP-ID             PIC X(5) VALUE "NONE".
      * report lines
       01 WS-SLIP-HEAD.
          05 FILLER             PIC X(4) VALUE "EMP ".
          05 SH-ID              PIC X(5).
          05 FILLER             PIC X VALUE SPACE.
          05 SH-NAME            PIC X(15).
          05 FILLER             PIC X(6) VALUE " DEPT ".
          05 SH-DEPT            PIC 9.
          05 FILLER             PIC X(6) VALUE " TYPE ".
          05 SH-TYPE            PIC X.
          05 FILLER             PIC X(5) VALUE " TAX ".
          05 SH-TAXCODE         PIC X.
       01 WS-SLIP-HOURS.
          05 FILLER             PIC X(8) VALUE "  HOURS ".
          05 SL-HOURS           PIC ZZ9.9.
          05 FILLER             PIC X(4) VALUE " OT ".
          05 SL-OT              PIC ZZ9.9.
          05 FILLER             PIC X(4) VALUE " DT ".
          05 SL-DT              PIC ZZ9.9.
          05 FILLER             PIC X(7) VALUE " GROSS ".
          05 SL-GROSS           PIC Z,ZZZ,ZZ9.99-.
       01 WS-SLIP-DEDUCT.
          05 FILLER             PIC X(6) VALUE "  TAX ".
          05 SL-TAX             PIC Z,ZZZ,ZZ9.99-.
          05 FILLER             PIC X(9) VALUE " PENSION ".
          05 SL-PENSION         PIC ZZ,ZZ9.99-.
          05 FILLER             PIC X(8) VALUE " HEALTH ".
          05 SL-HEALTH          PIC ZZ9.99.
          05 FILLER             PIC X(5) VALUE " NET ".
          05 SL-NET             PIC ZZZ,ZZ9.99-.
       01 WS-SLIP-ERROR.
          05 FILLER             PIC X(4) VALUE "EMP ".
          05 SE-ID              PIC X(5).
          05 FILLER             PIC X(8) VALUE " ERROR: ".
          05 SE-MSG             PIC X(16).
       01 WS-SUMMARY-LINE.
          05 FILLER             PIC X(5) VALUE "DEPT ".
          05 SM-DEPT            PIC 9.
          05 FILLER             PIC X(7) VALUE " COUNT ".
          05 SM-COUNT           PIC ZZ9.
          05 FILLER             PIC X(7) VALUE " GROSS ".
          05 SM-GROSS           PIC $$,$$$,$$9.99.
          05 FILLER             PIC X(5) VALUE " NET ".
          05 SM-NET             PIC $$,$$$,$$9.99.
          05 FILLER             PIC X(5) VALUE " AVG ".
          05 SM-AVG             PIC Z,ZZZ,ZZ9.99-.
          05 FILLER             PIC X VALUE SPACE.
          05 SM-FLAG            PIC X(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT EMP-FILE
           OPEN OUTPUT SLIP-FILE
           OPEN OUTPUT PAY-FILE
           INITIALIZE WS-DEPT-TOTALS
           PERFORM READ-EMPLOYEE
           PERFORM UNTIL END-OF-EMPLOYEES
               PERFORM PROCESS-EMPLOYEE
               PERFORM READ-EMPLOYEE
           END-PERFORM
           PERFORM WRITE-DEPT-SUMMARY
           CLOSE EMP-FILE
           CLOSE SLIP-FILE
           CLOSE PAY-FILE
           PERFORM SHOW-TOTALS
           STOP RUN.
       READ-EMPLOYEE.
           READ EMP-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   ADD 1 TO WS-READ-COUNT
           END-READ.
       PROCESS-EMPLOYEE.
           INITIALIZE WS-PAY-WORK
           PERFORM VALIDATE-EMPLOYEE
           IF WS-ERROR-MSG = SPACES
               PERFORM CALC-GROSS
           END-IF
           IF WS-ERROR-MSG = SPACES
               PERFORM CALC-DEDUCTIONS
           END-IF
           IF WS-ERROR-MSG = SPACES
               PERFORM ACCUMULATE
               PERFORM WRITE-PAYSLIP
               PERFORM WRITE-PAY-RECORD
           ELSE
               ADD 1 TO WS-ERROR-COUNT
               MOVE EMP-ID TO SE-ID
               MOVE WS-ERROR-MSG TO SE-MSG
               WRITE SLIP-REC FROM WS-SLIP-ERROR
           END-IF.
       VALIDATE-EMPLOYEE.
           EVALUATE TRUE
               WHEN EMP-ID = SPACES
                   MOVE "MISSING ID" TO WS-ERROR-MSG
               WHEN EMP-DEPT IS NOT NUMERIC
                   MOVE "BAD DEPT" TO WS-ERROR-MSG
               WHEN NOT DEPT-VALID
                   MOVE "BAD DEPT" TO WS-ERROR-MSG
               WHEN NOT TYPE-VALID
                   MOVE "BAD TYPE" TO WS-ERROR-MSG
               WHEN EMP-HOURS IS NOT NUMERIC
                   MOVE "BAD HOURS" TO WS-ERROR-MSG
               WHEN EMP-RATE IS NOT NUMERIC
                   MOVE "BAD RATE" TO WS-ERROR-MSG
               WHEN EMP-SALES IS NOT NUMERIC
                   MOVE "BAD SALES" TO WS-ERROR-MSG
               WHEN EMP-ALLOW IS NOT NUMERIC
                   MOVE "BAD ALLOWANCE" TO WS-ERROR-MSG
               WHEN OTHER
                   MOVE EMP-DEPT TO WS-DEPT
                   MOVE EMP-HOURS TO WS-HOURS
                   MOVE EMP-RATE TO WS-RATE
                   MOVE EMP-SALES TO WS-SALES
                   MOVE EMP-ALLOW TO WS-ALLOW
                   EVALUATE EMP-TAXCODE
                       WHEN "A"
                           MOVE 1 TO WS-TAX-IDX
                       WHEN "B"
                           MOVE 2 TO WS-TAX-IDX
                       WHEN "C"
                           MOVE 3 TO WS-TAX-IDX
                       WHEN OTHER
                           MOVE 4 TO WS-TAX-IDX
                   END-EVALUATE
           END-EVALUATE.
       CALC-GROSS.
           EVALUATE TRUE ALSO TRUE
               WHEN TYPE-HOURLY ALSO WS-HOURS > 40
                   PERFORM SPLIT-HOURS
                   PERFORM CALC-HOURLY
               WHEN TYPE-HOURLY ALSO ANY
                   MOVE WS-HOURS TO WS-REG-HOURS
                   PERFORM CALC-HOURLY
               WHEN TYPE-SALARIED ALSO ANY
                   COMPUTE WS-GROSS = WS-RATE + WS-ALLOW
               WHEN OTHER
                   PERFORM CALC-COMMISSION
           END-EVALUATE.
       SPLIT-HOURS.
           MOVE 40 TO WS-REG-HOURS
           COMPUTE WS-OT-HOURS = WS-HOURS - 40
           IF WS-OT-HOURS > 20
               COMPUTE WS-DT-HOURS = WS-OT-HOURS - 20
               MOVE 20 TO WS-OT-HOURS
           END-IF.
       CALC-HOURLY.
           COMPUTE WS-GROSS ROUNDED = WS-REG-HOURS * WS-RATE
                   + WS-OT-HOURS * WS-RATE * 1.5
                   + WS-DT-HOURS * WS-RATE * 2
                   + WS-ALLOW
               ON SIZE ERROR
                   MOVE "GROSS OVERFLOW" TO WS-ERROR-MSG
           END-COMPUTE.
       CALC-COMMISSION.
           PERFORM VARYING WS-TIER FROM 1 BY 1
                   UNTIL WS-TIER > 3
                      OR WS-SALES NOT > WS-TIER-LIMIT (WS-TIER)
               CONTINUE
           END-PERFORM
           COMPUTE WS-COMMISSION ROUNDED =
                   WS-SALES * WS-TIER-RATE (WS-TIER)
           COMPUTE WS-GROSS = WS-RATE + WS-COMMISSION + WS-ALLOW.
       CALC-DEDUCTIONS.
           MOVE WS-HEALTH-RATE (WS-DEPT) TO WS-HEALTH
           COMPUTE WS-TAXABLE = WS-GROSS - WS-TAX-EXEMPT (WS-TAX-IDX)
           IF WS-TAXABLE > 0
               COMPUTE WS-TAX ROUNDED =
                       WS-TAXABLE * WS-TAX-RATE (WS-TAX-IDX)
           ELSE
               MOVE 0 TO WS-TAX
           END-IF
           IF WS-GROSS > 5000
               COMPUTE WS-SURTAX = (WS-GROSS - 5000) * 0.01
               ADD WS-SURTAX TO WS-TAX
           END-IF
           IF WS-GROSS > 0
      *        no SIZE ERROR phrase: high-order digits are lost
               COMPUTE WS-PENSION = WS-GROSS * 0.05
           ELSE
               MOVE 0 TO WS-PENSION
           END-IF
           COMPUTE WS-NET = WS-GROSS - WS-TAX - WS-PENSION - WS-HEALTH
               ON SIZE ERROR
                   MOVE "NET OVERFLOW" TO WS-ERROR-MSG
           END-COMPUTE.
       ACCUMULATE.
           ADD 1 TO WS-PAID-COUNT
           ADD 1 TO DT-COUNT (WS-DEPT)
           ADD WS-GROSS TO DT-GROSS (WS-DEPT) WS-TOTAL-GROSS
           ADD WS-NET TO DT-NET (WS-DEPT) WS-TOTAL-NET
           IF WS-NET > WS-TOP-NET
               MOVE WS-NET TO WS-TOP-NET
               MOVE EMP-ID TO WS-TOP-ID
           END-IF.
       WRITE-PAYSLIP.
           MOVE EMP-ID TO SH-ID
           MOVE EMP-NAME TO SH-NAME
           MOVE WS-DEPT TO SH-DEPT
           MOVE EMP-TYPE TO SH-TYPE
           MOVE EMP-TAXCODE TO SH-TAXCODE
           WRITE SLIP-REC FROM WS-SLIP-HEAD
           MOVE WS-HOURS TO SL-HOURS
           MOVE WS-OT-HOURS TO SL-OT
           MOVE WS-DT-HOURS TO SL-DT
           MOVE WS-GROSS TO SL-GROSS
           WRITE SLIP-REC FROM WS-SLIP-HOURS
           MOVE WS-TAX TO SL-TAX
           MOVE WS-PENSION TO SL-PENSION
           MOVE WS-HEALTH TO SL-HEALTH
           MOVE WS-NET TO SL-NET
           WRITE SLIP-REC FROM WS-SLIP-DEDUCT.
       WRITE-PAY-RECORD.
           MOVE EMP-ID TO PR-ID
           MOVE WS-DEPT TO PR-DEPT
           MOVE EMP-TYPE TO PR-TYPE
           MOVE WS-HOURS TO PR-HOURS
           COMPUTE PR-OT-HOURS = WS-OT-HOURS + WS-DT-HOURS
           MOVE WS-GROSS TO PR-GROSS
           MOVE WS-TAX TO PR-TAX
           MOVE WS-NET TO PR-NET
           MOVE WS-ALLOW TO PR-ALLOW
           MOVE WS-PAID-COUNT TO PR-SEQ
           WRITE PAY-REC.
       WRITE-DEPT-SUMMARY.
           PERFORM VARYING WS-D FROM 1 BY 1 UNTIL WS-D > 5
               MOVE WS-D TO SM-DEPT
               MOVE DT-COUNT (WS-D) TO SM-COUNT
               MOVE DT-GROSS (WS-D) TO SM-GROSS
               MOVE DT-NET (WS-D) TO SM-NET
               COMPUTE WS-AVG-NET ROUNDED =
                       DT-NET (WS-D) / DT-COUNT (WS-D)
                   ON SIZE ERROR
                       MOVE 0 TO WS-AVG-NET
                       MOVE "N/A" TO SM-FLAG
                   NOT ON SIZE ERROR
                       MOVE "OK" TO SM-FLAG
               END-COMPUTE
               MOVE WS-AVG-NET TO SM-AVG
               WRITE SLIP-REC FROM WS-SUMMARY-LINE
           END-PERFORM.
       SHOW-TOTALS.
           DISPLAY "EMPLOYEES " WS-READ-COUNT " PAID " WS-PAID-COUNT
                   " ERRORS " WS-ERROR-COUNT
           DISPLAY "GROSS " WS-TOTAL-GROSS " NET " WS-TOTAL-NET
           DISPLAY "TOP EARNER " WS-TOP-ID " NET " WS-TOP-NET
           IF WS-ERROR-COUNT > 0
               MOVE 4 TO RETURN-CODE
           END-IF.
