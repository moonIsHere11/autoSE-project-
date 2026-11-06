       IDENTIFICATION DIVISION.
       PROGRAM-ID. S6TIME.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-D   PIC 9(6).
       01 WS-T   PIC 9(8).
       01 WS-CD  PIC X(21).
       01 WS-L1  PIC X(10).
       01 WS-L2  PIC X(10).
       PROCEDURE DIVISION.
           ACCEPT WS-D FROM DATE
           ACCEPT WS-T FROM TIME
           MOVE FUNCTION CURRENT-DATE TO WS-CD
           DISPLAY "DATE " WS-D " TIME " WS-T " CD " WS-CD
           ACCEPT WS-L1
           ACCEPT WS-L2
           DISPLAY "L1 [" WS-L1 "] L2 [" WS-L2 "]"
           STOP RUN.
