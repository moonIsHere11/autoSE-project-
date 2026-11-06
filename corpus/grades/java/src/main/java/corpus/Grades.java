package corpus;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

/**
 * Hand translation of GRADES. Numeric WORKING-STORAGE items are {@code long}s scaled by
 * 10^scale; OCCURS tables are {@code long[]} (index 0 = COBOL subscript 1). Input record
 * fields are kept as their raw text because they may hold non-numeric data (IS NUMERIC).
 */
public class Grades {
    private static final int IN_REC_LEN = 26;

    // FD GRADE-IN
    String inId = "    ";             // X(4)
    String inName = spaces(10);       // X(10)
    String inScore1 = "   ";          // 9(3) (raw text)
    String inScore2 = "   ";
    String inScore3 = "   ";
    String inScore4 = "   ";

    // WORKING-STORAGE
    String wsEof = "N";               // X VALUE "N"
    long[] wsWeight = {20, 20, 25, 35}; // 9(2) OCCURS 4 (REDEFINES of FILLER values)
    long[] wsScore = new long[4];     // 9(3) OCCURS 4
    String wsId = "    ";             // X(4)
    long wsI;                         // 9
    long wsBadCount;                  // 9
    long wsTotal;                     // 9(3)
    long wsWeightedSum;               // 9(5)
    long wsWeighted;                  // 9(3)V9, scale 1
    long wsAverage;                   // 9(3)V99, scale 2
    long wsAverageR;                  // 9(3)V9, scale 1
    long wsBest;                      // 9(3)
    long wsWorst;                     // 9(3)
    long wsGradeIdx;                  // 9
    String wsLetters = "ABCDF";       // X(5)
    String wsLetter = " ";            // X
    long[] wsGradeCount = new long[5]; // 9(3) OCCURS 5
    long wsStudents = 0;              // 9(3)
    long wsRejects = 0;               // 9(3)
    long wsClassSum = 0;              // 9(6)V9, scale 1
    long wsClassAvg = 0;              // 9(3)V99, scale 2
    String wsClassFlag = "   ";       // X(3)
    long wsTopScore = 0;              // 9(3)V9, scale 1
    String wsTopId = "    ";          // X(4)
    String wsStars = "********************"; // X(20) VALUE ALL "*"
    long wsBarLen;                    // 9(2)
    int returnCode;

    private List<String> inRecords;
    private int inPos;
    private final StringBuilder outFile = new StringBuilder();
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Grades p = new Grades();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        inRecords = lineSeqRecords(Files.readAllBytes(Paths.get("GRADES.IN")), IN_REC_LEN);
        inPos = 0;
        for (int k = 0; k < 5; k++) {
            wsGradeCount[k] = 0; // INITIALIZE
        }
        readNext();
        while (!wsEof.equals("Y")) {
            processRecord();
        }
        classSummary();
        writeSummary();
        Files.write(Paths.get("GRADES.OUT"), outFile.toString().getBytes(StandardCharsets.ISO_8859_1));
        line("STUDENTS " + unsigned(wsStudents, 3, 0) + " REJECTED " + unsigned(wsRejects, 3, 0));
        line("CLASS AVERAGE " + unsigned(wsClassAvg, 3, 2) + " " + wsClassFlag);
        if (wsRejects > 0) {
            returnCode = 4;
        }
    }

    void readNext() {
        if (inPos >= inRecords.size()) {
            wsEof = "Y";
            return;
        }
        String rec = inRecords.get(inPos++);
        inId = rec.substring(0, 4);
        inName = rec.substring(4, 14);
        inScore1 = rec.substring(14, 17);
        inScore2 = rec.substring(17, 20);
        inScore3 = rec.substring(20, 23);
        inScore4 = rec.substring(23, 26);
    }

    void processRecord() {
        loadScores();
        scoreStudent();
        if (wsBadCount == 0) {
            writeDetail();
        } else {
            writeReject();
        }
        readNext();
    }

    void loadScores() {
        wsId = inId;
        wsScore[0] = 999;
        wsScore[1] = 999;
        wsScore[2] = 999;
        wsScore[3] = 999;
        if (isNumeric(inScore1)) {
            wsScore[0] = Long.parseLong(inScore1);
        }
        if (isNumeric(inScore2)) {
            wsScore[1] = Long.parseLong(inScore2);
        }
        if (isNumeric(inScore3)) {
            wsScore[2] = Long.parseLong(inScore3);
        }
        if (isNumeric(inScore4)) {
            wsScore[3] = Long.parseLong(inScore4);
        }
    }

    void scoreStudent() {
        wsTotal = 0;
        wsWeightedSum = 0;
        wsBadCount = 0;
        wsBest = 0;
        wsWorst = 999;
        for (wsI = 1; wsI <= 4; wsI++) {
            long s = wsScore[(int) wsI - 1];
            if (s >= 0 && s <= 100) {                       // VALID-SCORE
                wsTotal = (wsTotal + s) % 1000;
                wsWeightedSum = (wsWeightedSum + s * wsWeight[(int) wsI - 1]) % 100000;
                if (s > wsBest) {
                    wsBest = s;
                }
                if (s < wsWorst) {
                    wsWorst = s;
                }
            } else {
                wsBadCount = (wsBadCount + 1) % 10;
            }
        }
        boolean blankId = true;
        for (int k = 0; k < 4; k++) {
            if (wsId.charAt(k) != ' ') {
                blankId = false;
            }
        }
        if (blankId) {
            wsBadCount = 9;
        }
        if (wsBadCount == 0) {
            long n = wsWeightedSum * 10;                    // WS-WEIGHTED-SUM / 100 at scale 1
            long q = n / 100;
            if (2 * (n % 100) >= 100) {
                q++;
            }
            wsWeighted = q % 10000;
            wsAverage = (wsTotal * 100 / 4) % 100000;       // truncated, scale 2
            long a = wsTotal * 10;
            long qa = a / 4;
            if (2 * (a % 4) >= 4) {
                qa++;
            }
            wsAverageR = qa % 10000;                        // ROUNDED, scale 1
            if (wsWeighted >= 900 && wsWeighted <= 1000) {
                wsGradeIdx = 1;
            } else if (wsWeighted >= 750 && wsWeighted <= 899) {
                wsGradeIdx = 2;
            } else if (wsWeighted >= 600 && wsWeighted <= 749) {
                wsGradeIdx = 3;
            } else if (wsWeighted >= 400 && wsWeighted <= 599) {
                wsGradeIdx = 4;
            } else {
                wsGradeIdx = 5;
            }
            wsLetter = wsLetters.substring((int) wsGradeIdx - 1, (int) wsGradeIdx);
            wsGradeCount[(int) wsGradeIdx - 1] = (wsGradeCount[(int) wsGradeIdx - 1] + 1) % 1000;
            wsStudents = (wsStudents + 1) % 1000;
            wsClassSum = (wsClassSum + wsWeighted) % 10000000L;
            if (wsWeighted > wsTopScore) {
                wsTopScore = wsWeighted;
                wsTopId = wsId;
            }
        } else {
            wsRejects = (wsRejects + 1) % 1000;
        }
    }

    void writeDetail() {
        String rec = wsId + " " + justifyRight(inName, 12) + " " + unsigned(wsTotal, 3, 0) + " "
                + edit(wsWeighted) + " " + digits(wsAverage, 5) + " " + digits(wsAverageR, 4) + " "
                + unsigned(wsBest, 3, 0) + "-" + unsigned(wsWorst, 3, 0) + " " + wsLetter;
        writeLine(rec);
    }

    void writeReject() {
        writeLine("REJECT " + wsId + " BAD=" + unsigned(wsBadCount, 1, 0));
    }

    void classSummary() {
        if (wsStudents == 0) {
            wsClassFlag = "N/A";                            // divide by zero: size error
        } else {
            long n = wsClassSum * 10;                       // scale 1 -> 2
            long q = n / wsStudents;
            if (2 * (n % wsStudents) >= wsStudents) {
                q++;
            }
            if (q > 99999) {
                wsClassFlag = "N/A";
            } else {
                wsClassAvg = q;
                wsClassFlag = "OK ";
            }
        }
    }

    void writeSummary() {
        for (wsGradeIdx = 1; wsGradeIdx <= 5; wsGradeIdx++) {
            int k = (int) wsGradeIdx - 1;
            String letter = wsLetters.substring(k, k + 1);
            wsBarLen = wsGradeCount[k] % 100;
            if (wsGradeCount[k] > 20) {
                wsBarLen = 20;
            }
            String bar = spaces(20);
            if (wsBarLen > 0) {
                bar = pad(wsStars.substring(0, (int) wsBarLen), 20);
            }
            writeLine(letter + " " + unsigned(wsGradeCount[k], 3, 0) + " " + bar);
        }
        writeLine("STUDENTS " + unsigned(wsStudents, 3, 0) + " REJECTS " + unsigned(wsRejects, 3, 0)
                + " AVG " + digits(wsClassAvg, 5) + " " + wsClassFlag + " TOP " + wsTopId + " " + edit(wsTopScore));
    }

    // ---------------------------------------------------------------- runtime helpers

    private void line(String s) {
        out.append(s).append('\n');
    }

    /** LINE SEQUENTIAL WRITE: trailing spaces are removed and a newline appended. */
    private void writeLine(String rec) {
        int end = rec.length();
        while (end > 0 && rec.charAt(end - 1) == ' ') {
            end--;
        }
        outFile.append(rec, 0, end).append('\n');
    }

    /**
     * GnuCOBOL 3.2 LINE SEQUENTIAL READ: bytes up to '\n' fill the record (short lines are space
     * padded). When the record is full, one more byte is read: '\n' is consumed, anything else
     * (including end of file) makes the reader step back one byte, so an overlong line is split
     * into several records and a full-length last line without '\n' yields one extra record
     * holding its last byte.
     */
    static List<String> lineSeqRecords(byte[] data, int recLen) {
        List<String> recs = new ArrayList<>();
        String all = new String(data, StandardCharsets.ISO_8859_1);
        int n = all.length();
        int pos = 0;
        while (pos < n) {
            int start = pos;
            while (pos < n && all.charAt(pos) != '\n' && pos - start < recLen) {
                pos++;
            }
            String rec = all.substring(start, pos);
            if (rec.length() < recLen) {
                if (pos < n) {
                    pos++; // the newline
                }
            } else if (pos < n && all.charAt(pos) == '\n') {
                pos++;
            } else if (pos >= n) {
                pos = n - 1; // step back over the last byte at end of file
            }
            recs.add(pad(rec, recLen));
        }
        return recs;
    }

    private static boolean isNumeric(String s) {
        if (s.isEmpty()) {
            return false;
        }
        for (int k = 0; k < s.length(); k++) {
            if (s.charAt(k) < '0' || s.charAt(k) > '9') {
                return false;
            }
        }
        return true;
    }

    private static String spaces(int n) {
        return " ".repeat(n);
    }

    private static String pad(String s, int n) {
        return s.length() >= n ? s.substring(0, n) : s + spaces(n - s.length());
    }

    /** MOVE to an X(n) JUSTIFIED RIGHT field. */
    private static String justifyRight(String s, int n) {
        return s.length() >= n ? s.substring(s.length() - n) : spaces(n - s.length()) + s;
    }

    /** Raw digits of an unsigned numeric DISPLAY field with {@code n} digits (implied decimal point). */
    private static String digits(long v, int n) {
        StringBuilder sb = new StringBuilder(Long.toString(v));
        while (sb.length() < n) {
            sb.insert(0, '0');
        }
        return sb.toString();
    }

    /** DISPLAY of an unsigned numeric field. */
    private static String unsigned(long v, int intDigits, int scale) {
        StringBuilder sb = new StringBuilder(digits(v, intDigits + scale));
        if (scale > 0) {
            sb.insert(sb.length() - scale, '.');
        }
        return sb.toString();
    }

    /** Numeric-edited PIC ZZ9.9 for a value held at scale 1. */
    private static String edit(long v) {
        String whole = Long.toString(v / 10);
        return spaces(3 - whole.length()) + whole + "." + (v % 10);
    }
}
