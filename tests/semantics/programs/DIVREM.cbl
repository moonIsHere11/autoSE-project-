       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIVREM.
      * DIVIDE ... GIVING ... REMAINDER: sign of the remainder, scaled
      * operands, ROUNDED quotient (remainder uses the truncated one).
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 Q            PIC S9(3).
       01 R            PIC S9(3).
       01 QV           PIC S9(3)V9.
       01 RV           PIC S9(3)V99.
       01 UR           PIC 9(3).
       01 A            PIC S9(3) VALUE -17.
       01 B            PIC S9(3) VALUE 5.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DIVIDE 17 BY 5 GIVING Q REMAINDER R
           DISPLAY Q " " R
           DIVIDE A BY B GIVING Q REMAINDER R
           DISPLAY Q " " R
           DIVIDE B INTO A GIVING Q REMAINDER R
           DISPLAY Q " " R
           DIVIDE A BY -5 GIVING Q REMAINDER R
           DISPLAY Q " " R
           DIVIDE 17 BY -5 GIVING Q REMAINDER R
           DISPLAY Q " " R
           DIVIDE 10 BY 3 GIVING QV REMAINDER RV
           DISPLAY QV " " RV
           DIVIDE 10 BY 3 GIVING QV ROUNDED REMAINDER RV
           DISPLAY QV " " RV
           DIVIDE 20 BY 3 GIVING Q ROUNDED REMAINDER R
           DISPLAY Q " " R
           DIVIDE A BY B GIVING Q REMAINDER UR
           DISPLAY Q " " UR
           DIVIDE 7.5 BY 2 GIVING Q REMAINDER RV
           DISPLAY Q " " RV
           STOP RUN.
