       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRMANIP.
      *----------------------------------------------------------------
      * Text line analysis.  stdin: lines of up to 20 characters until
      * a line "END", an empty line (also end of input) or 20 lines.
      * For each line: upper-casing, character counts, trimmed length,
      * reversal, first two words, a composed output string and a
      * masked copy.
      * Targets (deliberately outside the T2b IR subset): INSPECT
      * TALLYING / REPLACING ALL / REPLACING LEADING / CONVERTING,
      * STRING with DELIMITED BY SIZE / SPACE / a two-space literal,
      * WITH POINTER and ON OVERFLOW, UNSTRING DELIMITED BY ALL SPACE,
      * reference modification with variable offset and length,
      * JUSTIFIED RIGHT, alphanumeric MOVE truncation and padding,
      * ACCEPT loop until a sentinel.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-LINE               PIC X(20).
          88 LINE-END           VALUE "END".
       01 WS-COUNT              PIC 9(2) VALUE 0.
       01 WS-UPPER              PIC X(20).
       01 WS-SPACES             PIC 9(2).
       01 WS-VOWELS             PIC 9(2).
       01 WS-DIGIT-COUNT        PIC 9(2).
       01 WS-LEN                PIC 9(2).
       01 WS-REVERSED           PIC X(20).
       01 WS-I                  PIC 9(2).
       01 WS-J                  PIC 9(2).
       01 WS-SHORT              PIC X(8).
       01 WS-RIGHT              PIC X(12) JUSTIFIED RIGHT.
       01 WS-FIRST-WORD         PIC X(10).
       01 WS-SECOND-WORD        PIC X(10).
       01 WS-OUT                PIC X(40).
       01 WS-PTR                PIC 9(2).
       01 WS-OVERFLOW           PIC X.
       01 WS-MASKED             PIC X(20).
       01 WS-TOTAL-VOWELS       PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM GET-LINE
           PERFORM UNTIL LINE-END OR WS-LINE = SPACES
                   OR WS-COUNT NOT < 20
               PERFORM ANALYSE-LINE
               PERFORM BUILD-OUTPUT
               PERFORM SHOW-LINE
               PERFORM GET-LINE
           END-PERFORM
           DISPLAY "LINES " WS-COUNT " VOWELS " WS-TOTAL-VOWELS
           STOP RUN.
       GET-LINE.
           ACCEPT WS-LINE
           IF NOT LINE-END AND WS-LINE NOT = SPACES
               ADD 1 TO WS-COUNT
           END-IF.
       ANALYSE-LINE.
           MOVE WS-LINE TO WS-UPPER
           INSPECT WS-UPPER CONVERTING "abcdefghijklmnopqrstuvwxyz"
                                    TO "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
           MOVE 0 TO WS-SPACES WS-VOWELS WS-DIGIT-COUNT
           INSPECT WS-LINE TALLYING WS-SPACES FOR ALL SPACES
           INSPECT WS-UPPER TALLYING WS-VOWELS
                   FOR ALL "A" "E" "I" "O" "U"
           INSPECT WS-LINE TALLYING WS-DIGIT-COUNT
                   FOR ALL "0" "1" "2" "3" "4" "5" "6" "7" "8" "9"
           ADD WS-VOWELS TO WS-TOTAL-VOWELS
           MOVE 20 TO WS-LEN
           PERFORM UNTIL WS-LEN = 0
                   OR WS-LINE (WS-LEN:1) NOT = SPACE
               SUBTRACT 1 FROM WS-LEN
           END-PERFORM
           MOVE SPACES TO WS-REVERSED
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > WS-LEN
               COMPUTE WS-J = WS-LEN - WS-I + 1
               MOVE WS-LINE (WS-J:1) TO WS-REVERSED (WS-I:1)
           END-PERFORM.
       BUILD-OUTPUT.
           MOVE WS-LINE TO WS-SHORT
           MOVE WS-LINE (1:WS-LEN) TO WS-RIGHT
           MOVE SPACES TO WS-FIRST-WORD WS-SECOND-WORD
           UNSTRING WS-LINE DELIMITED BY ALL SPACE
               INTO WS-FIRST-WORD WS-SECOND-WORD
           END-UNSTRING
           MOVE SPACES TO WS-OUT
           MOVE "N" TO WS-OVERFLOW
           MOVE 1 TO WS-PTR
           STRING WS-FIRST-WORD DELIMITED BY SPACE
                  "/" DELIMITED BY SIZE
                  WS-UPPER (1:WS-LEN) DELIMITED BY SIZE
                  "/" DELIMITED BY SIZE
                  WS-REVERSED DELIMITED BY "  "
               INTO WS-OUT WITH POINTER WS-PTR
               ON OVERFLOW
                   MOVE "Y" TO WS-OVERFLOW
           END-STRING
           MOVE WS-LINE TO WS-MASKED
           INSPECT WS-MASKED REPLACING ALL "a" BY "4" "e" BY "3"
                                           "o" BY "0"
           INSPECT WS-MASKED REPLACING LEADING SPACE BY ".".
       SHOW-LINE.
           DISPLAY WS-COUNT " [" WS-LINE "] LEN " WS-LEN " SP "
                   WS-SPACES " VOW " WS-VOWELS " DIG " WS-DIGIT-COUNT
           DISPLAY "   UP [" WS-UPPER "] REV [" WS-REVERSED "]"
           DISPLAY "   SHORT [" WS-SHORT "] RIGHT [" WS-RIGHT
                   "] WORDS [" WS-FIRST-WORD "] [" WS-SECOND-WORD "]"
           DISPLAY "   OUT [" WS-OUT "] PTR " WS-PTR " OVF "
                   WS-OVERFLOW " MASK [" WS-MASKED "]".
