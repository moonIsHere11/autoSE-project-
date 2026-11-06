       IDENTIFICATION DIVISION.
       PROGRAM-ID. S6ACC.
      * ACCEPT the same text line into fields of different PICs and
      * DISPLAY the resulting value and the raw stored bytes.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N1        PIC 9(5).
       01 N1-R REDEFINES N1 PIC X(5).
       01 N2        PIC S9(5).
       01 N2-R REDEFINES N2 PIC X(5).
       01 N3        PIC S9(3)V99.
       01 N3-R REDEFINES N3 PIC X(5).
       01 N4        PIC 9(3)V99.
       01 N4-R REDEFINES N4 PIC X(5).
       01 X1        PIC X(5).
       01 N5        PIC S9(5) COMP-3.
       PROCEDURE DIVISION.
           ACCEPT N1
           ACCEPT N2
           ACCEPT N3
           ACCEPT N4
           ACCEPT X1
           ACCEPT N5
           DISPLAY "N1 9(5)     [" N1 "] raw [" N1-R "]"
           DISPLAY "N2 S9(5)    [" N2 "] raw [" N2-R "]"
           DISPLAY "N3 S9(3)V99 [" N3 "] raw [" N3-R "]"
           DISPLAY "N4 9(3)V99  [" N4 "] raw [" N4-R "]"
           DISPLAY "X1 X(5)     [" X1 "]"
           DISPLAY "N5 S9(5)C3  [" N5 "]"
           STOP RUN.
