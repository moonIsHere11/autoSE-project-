       IDENTIFICATION DIVISION.
       PROGRAM-ID. S6MORE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A-LS      PIC S9(3) SIGN LEADING SEPARATE.
       01 A-CB      PIC S9(4) COMP.
       01 A-C5      PIC S9(4) COMP-5.
       01 A-PV      PIC S9(3)V99 COMP-3.
       01 A-X3      PIC X(3).
       01 A-LIT     PIC X(40) VALUE "A   B  ""Q""  C".
       01 A-CONT    PIC X(60) VALUE "THIS IS A LONG LITERAL THAT IS CON
      -    "TINUED ON THE NEXT LINE".
       PROCEDURE DIVISION.
           ACCEPT A-LS
           ACCEPT A-CB
           ACCEPT A-C5
           ACCEPT A-PV
           ACCEPT A-X3
           DISPLAY "LS [" A-LS "] CB [" A-CB "] C5 [" A-C5 "] PV [" A-PV
               "] X3 [" A-X3 "]"
           DISPLAY "LIT [" A-LIT "]"
           DISPLAY "CONT [" A-CONT "]"
           STOP RUN.
