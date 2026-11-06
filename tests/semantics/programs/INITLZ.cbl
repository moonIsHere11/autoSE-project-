       IDENTIFICATION DIVISION.
       PROGRAM-ID. INITLZ.
      * INITIALIZE: alphanumerics to spaces, numerics to zero, FILLER
      * and REDEFINES untouched, COMP/COMP-3/edited/sign separate,
      * tables, elementary and group operands.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC.
          05 R-NAME    PIC X(4) VALUE "NAME".
          05 FILLER    PIC X(2) VALUE "FF".
          05 R-NUM     PIC S9(3) VALUE -12.
          05 R-PK      PIC S9(3) COMP-3 VALUE -7.
          05 R-BIN     PIC 9(4) COMP VALUE 513.
          05 R-ED      PIC ZZ9.99- VALUE "XXXXXXX".
          05 R-SS      PIC S99 SIGN LEADING SEPARATE VALUE -5.
          05 R-ALT REDEFINES R-SS PIC XXX.
          05 R-TAB OCCURS 2.
             10 T-X    PIC X VALUE "Q".
             10 T-N    PIC 9 VALUE 8.
       01 ONE          PIC X(3) VALUE "ABC".
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "[" REC "]"
           INITIALIZE REC
           DISPLAY "[" REC "]"
           MOVE ALL "Z" TO REC
           INITIALIZE R-TAB (2)
           DISPLAY "[" REC "]"
           INITIALIZE R-NUM R-NAME ONE
           DISPLAY "[" REC "] [" ONE "]"
           STOP RUN.
