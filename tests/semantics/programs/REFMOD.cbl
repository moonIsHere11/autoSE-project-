       IDENTIFICATION DIVISION.
       PROGRAM-ID. REFMOD.
      * Reference modification: literal and variable positions, open
      * length, numeric items viewed as characters, as receivers.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 T            PIC X(10) VALUE "ABCDEFGHIJ".
       01 N            PIC 9(6) VALUE 123456.
       01 S            PIC S9(4) VALUE -1234.
       01 P            PIC 9(2) VALUE 3.
       01 L            PIC 9(2) VALUE 4.
       01 D            PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY T (3:2) "|" T (P:L) "|" T (8:) "|" T (P + 1:1)
           DISPLAY N (2:3) "|" S (1:4) "|" S (4:1)
           MOVE "xy" TO T (5:2)
           DISPLAY T
           MOVE "12345" TO T (P:L)
           DISPLAY T
           MOVE N (6:1) TO D
           DISPLAY D
           MOVE T (1:3) TO N
           DISPLAY N
           MOVE "9" TO N (1:1)
           DISPLAY N
           STOP RUN.
