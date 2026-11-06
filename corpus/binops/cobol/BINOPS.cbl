       IDENTIFICATION DIVISION.
       PROGRAM-ID. BINOPS.
      *----------------------------------------------------------------
      * Binary and packed arithmetic.  stdin: three lines
      *   A PIC S9(4) COMP, B PIC S9(4) COMP-5, C PIC 9(3) COMP-3.
      * Targets: ACCEPT into COMP / COMP-3 (whole line, truncated to
      * the PIC) vs COMP-5 (not truncated to the PIC, wraps at 16
      * bits), binary-truncate on COMP / BINARY results, COMP-5
      * results not truncated to the PIC, ON SIZE ERROR on binary
      * targets, DIVIDE by a packed field (zero) with REMAINDER,
      * unsigned binary dropping the sign, big-endian COMP bytes seen
      * through REDEFINES, DISPLAY width of COMP-5 (binary capacity),
      * 88-levels on a binary field, RETURN-CODE from a COMP field.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A                  PIC S9(4) COMP.
          88 A-NEGATIVE         VALUE -9999 THRU -1.
          88 A-SMALL            VALUE 0 THRU 99.
       01 WS-B                  PIC S9(4) COMP-5.
       01 WS-C                  PIC 9(3) COMP-3.
       01 WS-SUM                PIC S9(4) COMP.
       01 WS-SUM-FLAG           PIC X(3).
       01 WS-PROD               PIC S9(6) BINARY.
       01 WS-PROD5              PIC S9(4) COMP-5.
       01 WS-WIDE5              PIC S9(4) COMP-5.
       01 WS-WIDE5-FLAG         PIC X(3).
       01 WS-DIFF-U             PIC 9(4) COMP.
       01 WS-SMALL              PIC 99 COMP.
       01 WS-QUOT               PIC S9(4) COMP VALUE 1111.
       01 WS-REM                PIC S9(3) COMP-3 VALUE 111.
       01 WS-DIV-FLAG           PIC X(4).
       01 WS-RAW-HOLDER.
          05 WS-RAW-NUM         PIC S9(4) COMP.
       01 WS-RAW-BYTES REDEFINES WS-RAW-HOLDER PIC X(2).
       01 WS-HI                 PIC 9(3).
       01 WS-LO                 PIC 9(3).
       01 WS-RC                 PIC 9(2) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM GET-INPUT
           PERFORM CALCULATE
           PERFORM SHOW-BYTES
           PERFORM SHOW-RESULTS
           MOVE WS-RC TO RETURN-CODE
           STOP RUN.
       GET-INPUT.
           ACCEPT WS-A
           ACCEPT WS-B
           ACCEPT WS-C.
       CALCULATE.
           ADD WS-A WS-B GIVING WS-SUM
               ON SIZE ERROR
                   MOVE "OVF" TO WS-SUM-FLAG
               NOT ON SIZE ERROR
                   MOVE "OK" TO WS-SUM-FLAG
           END-ADD
           MULTIPLY WS-A BY WS-B GIVING WS-PROD
           COMPUTE WS-PROD5 = WS-A * 3
           COMPUTE WS-WIDE5 = WS-B * 2
               ON SIZE ERROR
                   MOVE "OVF" TO WS-WIDE5-FLAG
               NOT ON SIZE ERROR
                   MOVE "OK" TO WS-WIDE5-FLAG
           END-COMPUTE
           SUBTRACT WS-A FROM WS-C GIVING WS-DIFF-U
           MOVE WS-B TO WS-SMALL
           DIVIDE WS-A BY WS-C GIVING WS-QUOT REMAINDER WS-REM
               ON SIZE ERROR
                   MOVE "ZERO" TO WS-DIV-FLAG
               NOT ON SIZE ERROR
                   MOVE "OK" TO WS-DIV-FLAG
           END-DIVIDE
           MOVE WS-A TO WS-RAW-NUM
           EVALUATE TRUE
               WHEN A-NEGATIVE
                   MOVE 3 TO WS-RC
               WHEN A-SMALL
                   MOVE 1 TO WS-RC
               WHEN OTHER
                   MOVE 2 TO WS-RC
           END-EVALUATE.
       SHOW-BYTES.
           COMPUTE WS-HI = FUNCTION ORD (WS-RAW-BYTES (1:1)) - 1
           COMPUTE WS-LO = FUNCTION ORD (WS-RAW-BYTES (2:1)) - 1.
       SHOW-RESULTS.
           DISPLAY "A " WS-A " B " WS-B " C " WS-C
           DISPLAY "SUM " WS-SUM " " WS-SUM-FLAG " PROD " WS-PROD
                   " PROD5 " WS-PROD5
           DISPLAY "WIDE5 " WS-WIDE5 " " WS-WIDE5-FLAG " DIFF-U "
                   WS-DIFF-U " SMALL " WS-SMALL
           DISPLAY "QUOT " WS-QUOT " REM " WS-REM " " WS-DIV-FLAG
           DISPLAY "BYTES " WS-HI " " WS-LO " RC " WS-RC.
