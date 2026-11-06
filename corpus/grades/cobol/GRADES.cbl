       IDENTIFICATION DIVISION.
       PROGRAM-ID. GRADES.
      *----------------------------------------------------------------
      * Student grade report.  Reads GRADES.IN (LINE SEQUENTIAL, one
      * student per line: id X(4), name X(10), four scores 9(3)),
      * writes GRADES.OUT (LINE SEQUENTIAL detail, reject and summary
      * lines) and a short summary on stdout.
      * Targets: OCCURS tables (one loaded by REDEFINES of FILLER
      * VALUEs), PERFORM VARYING, 88-levels with THRU on a decimal
      * field and on a table element, EVALUATE TRUE, ROUNDED vs
      * truncation, ON SIZE ERROR for an empty class, JUSTIFIED RIGHT,
      * reference modification with a variable start / length,
      * numeric-edited output, IS NUMERIC validation, RETURN-CODE 4.
      *----------------------------------------------------------------
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GRADE-IN ASSIGN TO "GRADES.IN"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT GRADE-OUT ASSIGN TO "GRADES.OUT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD GRADE-IN.
       01 IN-REC.
          05 IN-ID              PIC X(4).
          05 IN-NAME            PIC X(10).
          05 IN-SCORE-1         PIC 9(3).
          05 IN-SCORE-2         PIC 9(3).
          05 IN-SCORE-3         PIC 9(3).
          05 IN-SCORE-4         PIC 9(3).
       FD GRADE-OUT.
       01 OUT-REC               PIC X(60).
       WORKING-STORAGE SECTION.
       01 WS-EOF                PIC X VALUE "N".
          88 END-OF-FILE        VALUE "Y".
       01 WS-WEIGHT-VALUES.
          05 FILLER             PIC 9(2) VALUE 20.
          05 FILLER             PIC 9(2) VALUE 20.
          05 FILLER             PIC 9(2) VALUE 25.
          05 FILLER             PIC 9(2) VALUE 35.
       01 WS-WEIGHT-TABLE REDEFINES WS-WEIGHT-VALUES.
          05 WS-WEIGHT          PIC 9(2) OCCURS 4 TIMES.
       01 WS-SCORE-TABLE.
          05 WS-SCORE           PIC 9(3) OCCURS 4 TIMES.
             88 VALID-SCORE     VALUE 0 THRU 100.
       01 WS-ID                 PIC X(4).
       01 WS-I                  PIC 9.
       01 WS-BAD-COUNT          PIC 9.
       01 WS-TOTAL              PIC 9(3).
       01 WS-WEIGHTED-SUM       PIC 9(5).
       01 WS-WEIGHTED           PIC 9(3)V9.
          88 GRADE-A            VALUE 90 THRU 100.
          88 GRADE-B            VALUE 75 THRU 89.9.
          88 GRADE-C            VALUE 60 THRU 74.9.
          88 GRADE-D            VALUE 40 THRU 59.9.
       01 WS-AVERAGE            PIC 9(3)V99.
       01 WS-AVERAGE-R          PIC 9(3)V9.
       01 WS-BEST               PIC 9(3).
       01 WS-WORST              PIC 9(3).
       01 WS-GRADE-IDX          PIC 9.
       01 WS-LETTERS            PIC X(5) VALUE "ABCDF".
       01 WS-LETTER             PIC X.
       01 WS-GRADE-COUNTS.
          05 WS-GRADE-COUNT     PIC 9(3) OCCURS 5 TIMES.
       01 WS-STUDENTS           PIC 9(3) VALUE 0.
       01 WS-REJECTS            PIC 9(3) VALUE 0.
       01 WS-CLASS-SUM          PIC 9(6)V9 VALUE 0.
       01 WS-CLASS-AVG          PIC 9(3)V99 VALUE 0.
       01 WS-CLASS-FLAG         PIC X(3).
       01 WS-TOP-SCORE          PIC 9(3)V9 VALUE 0.
       01 WS-TOP-ID             PIC X(4) VALUE SPACES.
       01 WS-STARS              PIC X(20) VALUE ALL "*".
       01 WS-BAR-LEN            PIC 9(2).
       01 WS-DETAIL.
          05 WS-D-ID            PIC X(4).
          05 FILLER             PIC X VALUE SPACE.
          05 WS-D-NAME          PIC X(12) JUSTIFIED RIGHT.
          05 FILLER             PIC X VALUE SPACE.
          05 WS-D-TOTAL         PIC 9(3).
          05 FILLER             PIC X VALUE SPACE.
          05 WS-D-WEIGHTED      PIC ZZ9.9.
          05 FILLER             PIC X VALUE SPACE.
          05 WS-D-AVERAGE       PIC 9(3)V99.
          05 FILLER             PIC X VALUE SPACE.
          05 WS-D-AVERAGE-R     PIC 9(3)V9.
          05 FILLER             PIC X VALUE SPACE.
          05 WS-D-BEST          PIC 9(3).
          05 FILLER             PIC X VALUE "-".
          05 WS-D-WORST         PIC 9(3).
          05 FILLER             PIC X VALUE SPACE.
          05 WS-D-LETTER        PIC X.
       01 WS-REJECT-LINE.
          05 FILLER             PIC X(7) VALUE "REJECT ".
          05 WS-R-ID            PIC X(4).
          05 FILLER             PIC X(5) VALUE " BAD=".
          05 WS-R-COUNT         PIC 9.
       01 WS-BAR-LINE.
          05 WS-B-LETTER        PIC X.
          05 FILLER             PIC X VALUE SPACE.
          05 WS-B-COUNT         PIC 9(3).
          05 FILLER             PIC X VALUE SPACE.
          05 WS-B-BAR           PIC X(20).
       01 WS-SUMMARY-LINE.
          05 FILLER             PIC X(9) VALUE "STUDENTS ".
          05 WS-S-STUDENTS      PIC 9(3).
          05 FILLER             PIC X(9) VALUE " REJECTS ".
          05 WS-S-REJECTS       PIC 9(3).
          05 FILLER             PIC X(5) VALUE " AVG ".
          05 WS-S-AVG           PIC 9(3)V99.
          05 FILLER             PIC X VALUE SPACE.
          05 WS-S-FLAG          PIC X(3).
          05 FILLER             PIC X(5) VALUE " TOP ".
          05 WS-S-TOP-ID        PIC X(4).
          05 FILLER             PIC X VALUE SPACE.
          05 WS-S-TOP           PIC ZZ9.9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT GRADE-IN
           OPEN OUTPUT GRADE-OUT
           INITIALIZE WS-GRADE-COUNTS
           PERFORM READ-NEXT
           PERFORM PROCESS-RECORD UNTIL END-OF-FILE
           PERFORM CLASS-SUMMARY
           PERFORM WRITE-SUMMARY
           CLOSE GRADE-IN
           CLOSE GRADE-OUT
           DISPLAY "STUDENTS " WS-STUDENTS " REJECTED " WS-REJECTS
           DISPLAY "CLASS AVERAGE " WS-CLASS-AVG " " WS-CLASS-FLAG
           IF WS-REJECTS > 0
               MOVE 4 TO RETURN-CODE
           END-IF
           STOP RUN.
       READ-NEXT.
           READ GRADE-IN
               AT END
                   MOVE "Y" TO WS-EOF
           END-READ.
       PROCESS-RECORD.
           PERFORM LOAD-SCORES
           PERFORM SCORE-STUDENT
           IF WS-BAD-COUNT = 0
               PERFORM WRITE-DETAIL
           ELSE
               PERFORM WRITE-REJECT
           END-IF
           PERFORM READ-NEXT.
       LOAD-SCORES.
           MOVE IN-ID TO WS-ID
           MOVE 999 TO WS-SCORE (1) WS-SCORE (2) WS-SCORE (3)
                       WS-SCORE (4)
           IF IN-SCORE-1 IS NUMERIC
               MOVE IN-SCORE-1 TO WS-SCORE (1)
           END-IF
           IF IN-SCORE-2 IS NUMERIC
               MOVE IN-SCORE-2 TO WS-SCORE (2)
           END-IF
           IF IN-SCORE-3 IS NUMERIC
               MOVE IN-SCORE-3 TO WS-SCORE (3)
           END-IF
           IF IN-SCORE-4 IS NUMERIC
               MOVE IN-SCORE-4 TO WS-SCORE (4)
           END-IF.
       SCORE-STUDENT.
           MOVE 0 TO WS-TOTAL WS-WEIGHTED-SUM WS-BAD-COUNT WS-BEST
           MOVE 999 TO WS-WORST
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 4
               IF VALID-SCORE (WS-I)
                   ADD WS-SCORE (WS-I) TO WS-TOTAL
                   COMPUTE WS-WEIGHTED-SUM = WS-WEIGHTED-SUM
                       + WS-SCORE (WS-I) * WS-WEIGHT (WS-I)
                   IF WS-SCORE (WS-I) > WS-BEST
                       MOVE WS-SCORE (WS-I) TO WS-BEST
                   END-IF
                   IF WS-SCORE (WS-I) < WS-WORST
                       MOVE WS-SCORE (WS-I) TO WS-WORST
                   END-IF
               ELSE
                   ADD 1 TO WS-BAD-COUNT
               END-IF
           END-PERFORM
           IF WS-ID = SPACES
               MOVE 9 TO WS-BAD-COUNT
           END-IF
           IF WS-BAD-COUNT = 0
               COMPUTE WS-WEIGHTED ROUNDED = WS-WEIGHTED-SUM / 100
               COMPUTE WS-AVERAGE = WS-TOTAL / 4
               COMPUTE WS-AVERAGE-R ROUNDED = WS-TOTAL / 4
               EVALUATE TRUE
                   WHEN GRADE-A
                       MOVE 1 TO WS-GRADE-IDX
                   WHEN GRADE-B
                       MOVE 2 TO WS-GRADE-IDX
                   WHEN GRADE-C
                       MOVE 3 TO WS-GRADE-IDX
                   WHEN GRADE-D
                       MOVE 4 TO WS-GRADE-IDX
                   WHEN OTHER
                       MOVE 5 TO WS-GRADE-IDX
               END-EVALUATE
               MOVE WS-LETTERS (WS-GRADE-IDX:1) TO WS-LETTER
               ADD 1 TO WS-GRADE-COUNT (WS-GRADE-IDX)
               ADD 1 TO WS-STUDENTS
               ADD WS-WEIGHTED TO WS-CLASS-SUM
               IF WS-WEIGHTED > WS-TOP-SCORE
                   MOVE WS-WEIGHTED TO WS-TOP-SCORE
                   MOVE WS-ID TO WS-TOP-ID
               END-IF
           ELSE
               ADD 1 TO WS-REJECTS
           END-IF.
       WRITE-DETAIL.
           MOVE WS-ID TO WS-D-ID
           MOVE IN-NAME TO WS-D-NAME
           MOVE WS-TOTAL TO WS-D-TOTAL
           MOVE WS-WEIGHTED TO WS-D-WEIGHTED
           MOVE WS-AVERAGE TO WS-D-AVERAGE
           MOVE WS-AVERAGE-R TO WS-D-AVERAGE-R
           MOVE WS-BEST TO WS-D-BEST
           MOVE WS-WORST TO WS-D-WORST
           MOVE WS-LETTER TO WS-D-LETTER
           WRITE OUT-REC FROM WS-DETAIL.
       WRITE-REJECT.
           MOVE WS-ID TO WS-R-ID
           MOVE WS-BAD-COUNT TO WS-R-COUNT
           WRITE OUT-REC FROM WS-REJECT-LINE.
       CLASS-SUMMARY.
           COMPUTE WS-CLASS-AVG ROUNDED = WS-CLASS-SUM / WS-STUDENTS
               ON SIZE ERROR
                   MOVE "N/A" TO WS-CLASS-FLAG
               NOT ON SIZE ERROR
                   MOVE "OK" TO WS-CLASS-FLAG
           END-COMPUTE.
       WRITE-SUMMARY.
           PERFORM VARYING WS-GRADE-IDX FROM 1 BY 1
                   UNTIL WS-GRADE-IDX > 5
               MOVE WS-LETTERS (WS-GRADE-IDX:1) TO WS-B-LETTER
               MOVE WS-GRADE-COUNT (WS-GRADE-IDX) TO WS-B-COUNT
               MOVE WS-GRADE-COUNT (WS-GRADE-IDX) TO WS-BAR-LEN
               IF WS-GRADE-COUNT (WS-GRADE-IDX) > 20
                   MOVE 20 TO WS-BAR-LEN
               END-IF
               MOVE SPACES TO WS-B-BAR
               IF WS-BAR-LEN > 0
                   MOVE WS-STARS (1:WS-BAR-LEN) TO WS-B-BAR
               END-IF
               WRITE OUT-REC FROM WS-BAR-LINE
           END-PERFORM
           MOVE WS-STUDENTS TO WS-S-STUDENTS
           MOVE WS-REJECTS TO WS-S-REJECTS
           MOVE WS-CLASS-AVG TO WS-S-AVG
           MOVE WS-CLASS-FLAG TO WS-S-FLAG
           MOVE WS-TOP-ID TO WS-S-TOP-ID
           MOVE WS-TOP-SCORE TO WS-S-TOP
           WRITE OUT-REC FROM WS-SUMMARY-LINE.
