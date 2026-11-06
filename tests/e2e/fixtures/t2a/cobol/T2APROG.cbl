       IDENTIFICATION DIVISION.
       PROGRAM-ID. T2APROG.
      * T2a fixture: two small ACCEPTs, so the whole canonical input
      * domain is 100 x 10 = 1000 cases.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-QTY      PIC 9(2).
       01 WS-CODE     PIC 9.
       01 WS-PRICE    PIC 9(3)V99.
       01 WS-TOTAL    PIC 9(4)V99.
       01 WS-DISC     PIC 9(3)V99.
       01 WS-NET      PIC S9(4)V99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-QTY
           ACCEPT WS-CODE
           PERFORM CALC-PARA
           DISPLAY "TOTAL=" WS-TOTAL " NET=" WS-NET
           STOP RUN.
       CALC-PARA.
           EVALUATE WS-CODE
               WHEN 0
                   MOVE 1.25 TO WS-PRICE
               WHEN 1 THRU 4
                   MOVE 19.99 TO WS-PRICE
               WHEN OTHER
                   MOVE 7.5 TO WS-PRICE
           END-EVALUATE
           COMPUTE WS-TOTAL ROUNDED = WS-QTY * WS-PRICE * 1.075
           IF WS-QTY > 50
               COMPUTE WS-DISC ROUNDED = WS-TOTAL * 0.125
           ELSE
               MOVE 0 TO WS-DISC
           END-IF
           SUBTRACT WS-DISC FROM WS-TOTAL GIVING WS-NET.
