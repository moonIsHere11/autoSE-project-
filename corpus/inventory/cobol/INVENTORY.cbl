       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVENTORY.
      *----------------------------------------------------------------
      * Stock valuation.  Reads STOCK.DAT (fixed-length SEQUENTIAL,
      * 21-byte records with COMP-3, COMP, overpunched zoned and
      * SIGN LEADING SEPARATE fields), writes VALUE.DAT (fixed-length
      * SEQUENTIAL, 32-byte records with COMP-3, COMP and SIGN
      * TRAILING SEPARATE fields) and a report on stdout.
      * Targets: binary/packed/zoned record encodings, IS NUMERIC on
      * packed and sign-separate fields, ADD / COMPUTE / MULTIPLY with
      * ON SIZE ERROR, ROUNDED, EVALUATE TRUE, MOVE with high-order
      * truncation into a sign-separate field, RETURN-CODE 0/4/8/12.
      *----------------------------------------------------------------
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT STOCK-FILE ASSIGN TO "STOCK.DAT"
               ORGANIZATION IS SEQUENTIAL.
           SELECT VALUE-FILE ASSIGN TO "VALUE.DAT"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD STOCK-FILE.
       01 STK-REC.
          05 STK-ITEM           PIC X(6).
          05 STK-QTY            PIC S9(5) COMP-3.
          05 STK-COST           PIC 9(4)V99 COMP-3.
          05 STK-REORDER        PIC S9(4) COMP.
          05 STK-ADJ            PIC S9(3).
          05 STK-DISC           PIC SV99 SIGN LEADING SEPARATE.
       FD VALUE-FILE.
       01 VAL-REC.
          05 VAL-ITEM           PIC X(6).
          05 VAL-NEW-QTY        PIC S9(5) COMP-3.
          05 VAL-UNIT           PIC S9(4)V99 COMP-3.
          05 VAL-AMOUNT         PIC S9(8)V99 COMP-3.
          05 VAL-COUNT          PIC 9(4) COMP.
          05 VAL-FLAG           PIC X.
          05 VAL-NET            PIC S9(7)V99 SIGN TRAILING SEPARATE.
       WORKING-STORAGE SECTION.
       01 WS-EOF                PIC X VALUE "N".
       01 WS-VALID              PIC X.
       01 WS-ITEM               PIC X(6).
       01 WS-QTY                PIC S9(5) COMP-3.
       01 WS-COST               PIC 9(4)V99 COMP-3.
       01 WS-REORDER            PIC S9(4) COMP.
       01 WS-ADJ                PIC S9(3).
       01 WS-DISC               PIC SV99 SIGN LEADING SEPARATE.
       01 WS-UNIT               PIC S9(4)V99 COMP-3.
       01 WS-AMOUNT             PIC S9(8)V99 COMP-3.
       01 WS-STATUS             PIC X.
          88 STATUS-OK          VALUE SPACE.
       01 WS-REC-COUNT          PIC 9(4) COMP VALUE 0.
       01 WS-REJECT-COUNT       PIC 9(4) COMP VALUE 0.
       01 WS-NEG-COUNT          PIC 9(4) COMP VALUE 0.
       01 WS-REORDER-COUNT      PIC 9(4) COMP VALUE 0.
       01 WS-TOTAL-VALUE        PIC S9(11)V99 COMP-3 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT STOCK-FILE
           OPEN OUTPUT VALUE-FILE
           PERFORM READ-STOCK
           PERFORM UNTIL WS-EOF = "Y"
               PERFORM VALIDATE-RECORD
               IF WS-VALID = "Y"
                   PERFORM VALUE-ITEM
               ELSE
                   PERFORM REJECT-ITEM
               END-IF
               PERFORM WRITE-VALUE
               PERFORM READ-STOCK
           END-PERFORM
           CLOSE STOCK-FILE
           CLOSE VALUE-FILE
           PERFORM SET-RETURN
           PERFORM SHOW-TOTALS
           STOP RUN.
       READ-STOCK.
           READ STOCK-FILE
               AT END
                   MOVE "Y" TO WS-EOF
           END-READ.
       VALIDATE-RECORD.
           MOVE "N" TO WS-VALID
           MOVE STK-ITEM TO WS-ITEM
           IF STK-QTY IS NUMERIC AND STK-COST IS NUMERIC
                   AND STK-ADJ IS NUMERIC AND STK-DISC IS NUMERIC
               MOVE "Y" TO WS-VALID
               MOVE STK-QTY TO WS-QTY
               MOVE STK-COST TO WS-COST
               MOVE STK-REORDER TO WS-REORDER
               MOVE STK-ADJ TO WS-ADJ
               MOVE STK-DISC TO WS-DISC
           END-IF.
       VALUE-ITEM.
           MOVE SPACE TO WS-STATUS
           ADD WS-ADJ TO WS-QTY
               ON SIZE ERROR
                   MOVE "O" TO WS-STATUS
           END-ADD
           COMPUTE WS-UNIT ROUNDED = WS-COST * (1 + WS-DISC)
               ON SIZE ERROR
                   MOVE WS-COST TO WS-UNIT
                   MOVE "P" TO WS-STATUS
           END-COMPUTE
           MULTIPLY WS-QTY BY WS-UNIT GIVING WS-AMOUNT
               ON SIZE ERROR
                   MOVE 0 TO WS-AMOUNT
                   MOVE "V" TO WS-STATUS
           END-MULTIPLY
           EVALUATE TRUE
               WHEN NOT STATUS-OK
                   CONTINUE
               WHEN WS-QTY < 0
                   MOVE "N" TO WS-STATUS
                   ADD 1 TO WS-NEG-COUNT
               WHEN WS-QTY < WS-REORDER
                   MOVE "R" TO WS-STATUS
                   ADD 1 TO WS-REORDER-COUNT
               WHEN OTHER
                   CONTINUE
           END-EVALUATE
           ADD WS-AMOUNT TO WS-TOTAL-VALUE.
       REJECT-ITEM.
           MOVE "X" TO WS-STATUS
           MOVE 0 TO WS-QTY WS-UNIT WS-AMOUNT
           ADD 1 TO WS-REJECT-COUNT.
       WRITE-VALUE.
           ADD 1 TO WS-REC-COUNT
           MOVE WS-ITEM TO VAL-ITEM
           MOVE WS-QTY TO VAL-NEW-QTY
           MOVE WS-UNIT TO VAL-UNIT
           MOVE WS-AMOUNT TO VAL-AMOUNT
           MOVE WS-REC-COUNT TO VAL-COUNT
           MOVE WS-STATUS TO VAL-FLAG
           MOVE WS-AMOUNT TO VAL-NET
           WRITE VAL-REC
           DISPLAY WS-REC-COUNT " " WS-ITEM " QTY " WS-QTY
                   " UNIT " WS-UNIT " AMOUNT " WS-AMOUNT
                   " [" WS-STATUS "] NET " VAL-NET.
       SET-RETURN.
           EVALUATE TRUE
               WHEN WS-REJECT-COUNT > 0
                   MOVE 12 TO RETURN-CODE
               WHEN WS-NEG-COUNT > 0
                   MOVE 8 TO RETURN-CODE
               WHEN WS-REORDER-COUNT > 0
                   MOVE 4 TO RETURN-CODE
               WHEN OTHER
                   MOVE 0 TO RETURN-CODE
           END-EVALUATE.
       SHOW-TOTALS.
           DISPLAY "RECORDS " WS-REC-COUNT " REJECTED " WS-REJECT-COUNT
                   " NEGATIVE " WS-NEG-COUNT " REORDER "
                   WS-REORDER-COUNT
           DISPLAY "TOTAL VALUE " WS-TOTAL-VALUE.
