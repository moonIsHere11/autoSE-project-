       IDENTIFICATION DIVISION.
       PROGRAM-ID. REDEF.
      * REDEFINES: numeric views of alphanumeric storage, packed and
      * binary views, 01-level REDEFINES, overlapping group moves.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC.
          05 TXT       PIC X(6) VALUE "123456".
          05 NUM REDEFINES TXT PIC 9(4)V99.
          05 PARTS REDEFINES TXT.
             10 P1     PIC 99.
             10 P2     PIC XX.
             10 P3     PIC 99.
       01 RAW          PIC X(4) VALUE X"0012345C".
       01 PK REDEFINES RAW PIC S9(7) COMP-3.
       01 BN REDEFINES RAW PIC S9(9) COMP.
       01 AREA1        PIC X(8) VALUE "ABCDEFGH".
       01 AREA2 REDEFINES AREA1.
          05 HALF1     PIC X(4).
          05 HALF2     PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY NUM " " P1 " " P2 " " P3
           ADD 1.01 TO NUM
           DISPLAY TXT " " NUM
           MOVE "XY" TO P2
           DISPLAY TXT
           DISPLAY PK " " BN
           ADD 1 TO PK
           DISPLAY PK " " BN
           MOVE -1 TO BN
           DISPLAY BN
           MOVE HALF1 TO HALF2
           DISPLAY AREA1
           MOVE "ZZ" TO AREA1 (3:2)
           DISPLAY AREA2
           STOP RUN.
