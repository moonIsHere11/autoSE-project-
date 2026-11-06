package corpus;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

/**
 * Hand translation of MERGE2. The COBOL control flow (GO TO, PERFORM ... THRU ... EXIT and the
 * fall-through from MAIN-PARA into MERGE-LOOP and FINISH) is reproduced with loops and explicit
 * calls; every paragraph, including the EXIT paragraphs, has its own method.
 * Signed zoned amounts are {@code long}s in cents plus a flag for a stored negative zero,
 * because MOVE keeps the sign of a "-0" overpunch and it shows in NEWMAST.TXT.
 */
public class Merge2 {
    private static final String HIGH_VALUES = "ÿÿÿÿÿ";
    private static final String LOW_VALUES = "\u0000\u0000\u0000\u0000\u0000";

    // FD records (raw text of the current record)
    String mstKey = "     ";
    String mstName = "          ";
    String mstBal = "0000000";       // S9(5)V99, raw zoned text
    String trnKey = "     ";
    String trnCode = " ";
    String trnName = "          ";
    String trnAmt = "0000000";       // S9(5)V99, raw zoned text
    String newKey = "     ";
    String newName = "          ";
    long newBal;                     // S9(5)V99, cents
    boolean newBalNegZero;

    // WORKING-STORAGE
    String wsMkey = "     ";
    String wsTkey = "     ";
    String wsPrevMkey = LOW_VALUES;
    String wsPrevTkey = LOW_VALUES;
    String wsMname = "          ";
    long wsBal;                      // S9(5)V99, cents
    boolean wsBalNegZero;
    String wsDeleted = "N";
    String wsMsg = spaces(20);
    long wsReadM = 0;
    long wsReadT = 0;
    long wsWritten = 0;
    long wsAdded = 0;
    long wsUpdated = 0;
    long wsDelCount = 0;
    long wsErrors = 0;
    int returnCode;

    private List<String> masterRecs;
    private int masterPos;
    private List<String> transRecs;
    private int transPos;
    private final StringBuilder newFile = new StringBuilder();
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Merge2 p = new Merge2();
        p.mainPara();
        Files.write(Paths.get("NEWMAST.TXT"), p.newFile.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        masterRecs = lineSeqRecords(Files.readAllBytes(Paths.get("MASTER.TXT")), 22);
        transRecs = lineSeqRecords(Files.readAllBytes(Paths.get("TRANS.TXT")), 23);
        readMaster();
        readMasterExit();
        readTrans();
        readTransExit();
        mergeLoop(); // fall-through
    }

    void mergeLoop() {
        while (true) {
            if (wsMkey.equals(HIGH_VALUES) && wsTkey.equals(HIGH_VALUES)) {
                finish();
                return;
            }
            if (wsMkey.compareTo(wsTkey) < 0) {
                copyMaster();
                readMaster();
                readMasterExit();
                continue;
            }
            if (wsMkey.equals(wsTkey)) {
                applyTrans();
                readTrans();
                readTransExit();
                continue;
            }
            addNew();
            readTrans();
            readTransExit();
        }
    }

    void finish() {
        line("MASTERS " + num(wsReadM, 3) + " TRANS " + num(wsReadT, 3) + " WRITTEN " + num(wsWritten, 3)
                + " ADDED " + num(wsAdded, 3));
        line("UPDATED " + num(wsUpdated, 3) + " DELETED " + num(wsDelCount, 3) + " ERRORS " + num(wsErrors, 3));
        if (wsErrors > 0) {
            returnCode = 4;
        }
    }

    void readMaster() {
        while (true) {
            if (masterPos >= masterRecs.size()) {
                wsMkey = HIGH_VALUES;
                return; // GO TO READ-MASTER-EXIT
            }
            String rec = masterRecs.get(masterPos++);
            mstKey = rec.substring(0, 5);
            mstName = rec.substring(5, 15);
            mstBal = rec.substring(15, 22);
            wsReadM = (wsReadM + 1) % 1000;
            if (!zonedIsNumeric(mstBal)) {
                line("BAD MASTER [" + mstKey + "]");
                wsErrors = (wsErrors + 1) % 1000;
                continue; // GO TO READ-MASTER
            }
            if (mstKey.compareTo(wsPrevMkey) <= 0) {
                line("MASTER OUT OF SEQUENCE [" + mstKey + "]");
                wsErrors = (wsErrors + 1) % 1000;
                continue;
            }
            wsMkey = mstKey;
            wsPrevMkey = mstKey;
            wsMname = mstName;
            wsBal = zonedValue(mstBal);
            wsBalNegZero = zonedNegZero(mstBal);
            wsDeleted = "N";
            return;
        }
    }

    void readMasterExit() {
        // EXIT
    }

    void readTrans() {
        while (true) {
            if (transPos >= transRecs.size()) {
                wsTkey = HIGH_VALUES;
                return;
            }
            String rec = transRecs.get(transPos++);
            trnKey = rec.substring(0, 5);
            trnCode = rec.substring(5, 6);
            trnName = rec.substring(6, 16);
            trnAmt = rec.substring(16, 23);
            wsReadT = (wsReadT + 1) % 1000;
            if (!zonedIsNumeric(trnAmt)) {
                line("BAD TRANS [" + trnKey + "]");
                wsErrors = (wsErrors + 1) % 1000;
                continue;
            }
            if (trnKey.compareTo(wsPrevTkey) < 0) {
                line("TRANS OUT OF SEQUENCE [" + trnKey + "]");
                wsErrors = (wsErrors + 1) % 1000;
                continue;
            }
            wsTkey = trnKey;
            wsPrevTkey = trnKey;
            return;
        }
    }

    void readTransExit() {
        // EXIT
    }

    void copyMaster() {
        if (wsDeleted.equals("N")) {
            newKey = wsMkey;
            newName = wsMname;
            newBal = wsBal;
            newBalNegZero = wsBalNegZero;
            writeNewRec();
            wsWritten = (wsWritten + 1) % 1000;
        }
    }

    void applyTrans() {
        if (wsDeleted.equals("Y")) {
            wsMsg = pad("ALREADY DELETED", 20);
            applyError();
            applyTransExit();
            return;
        }
        if (trnCode.equals("U")) {
            long sum = wsBal + zonedValue(trnAmt);
            if (sum > 9999999L || sum < -9999999L) {
                wsMsg = pad("BALANCE OVERFLOW", 20);
                applyError();
                applyTransExit();
                return;
            }
            wsBal = sum;
            wsBalNegZero = false;
            wsUpdated = (wsUpdated + 1) % 1000;
        } else if (trnCode.equals("D")) {
            wsDeleted = "Y";
            wsDelCount = (wsDelCount + 1) % 1000;
        } else if (trnCode.equals("A")) {
            wsMsg = pad("DUPLICATE KEY", 20);
            applyError();
            applyTransExit();
            return;
        } else {
            wsMsg = pad("BAD CODE", 20);
            applyError();
            applyTransExit();
            return;
        }
        applyTransExit(); // GO TO APPLY-TRANS-EXIT
    }

    void applyError() {
        wsErrors = (wsErrors + 1) % 1000;
        line("ERROR [" + trnKey + "] " + trnCode + " " + wsMsg);
    }

    void applyTransExit() {
        // EXIT
    }

    void addNew() {
        if (!trnCode.equals("A")) {
            wsMsg = pad("NO MASTER", 20);
            wsErrors = (wsErrors + 1) % 1000;
            line("ERROR [" + trnKey + "] " + trnCode + " " + wsMsg);
            addNewExit();
            return;
        }
        newKey = trnKey;
        newName = trnName;
        newBal = zonedValue(trnAmt);
        newBalNegZero = zonedNegZero(trnAmt);
        writeNewRec();
        wsAdded = (wsAdded + 1) % 1000;
        wsWritten = (wsWritten + 1) % 1000;
        addNewExit();
    }

    void addNewExit() {
        // EXIT
    }

    // ---------------------------------------------------------------- runtime helpers

    private void writeNewRec() {
        String rec = newKey + newName + zoned(newBal, newBalNegZero, 7);
        int end = rec.length();
        while (end > 0 && rec.charAt(end - 1) == ' ') {
            end--;
        }
        newFile.append(rec, 0, end).append('\n');
    }

    private void line(String s) {
        out.append(s).append('\n');
    }

    /** IS NUMERIC for a signed zoned field with a trailing embedded (overpunch) sign. */
    private static boolean zonedIsNumeric(String s) {
        for (int i = 0; i < s.length() - 1; i++) {
            if (s.charAt(i) < '0' || s.charAt(i) > '9') {
                return false;
            }
        }
        char last = s.charAt(s.length() - 1);
        return (last >= '0' && last <= '9') || (last >= 'p' && last <= 'y');
    }

    private static long zonedValue(String s) {
        long v = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            v = v * 10 + (c >= 'p' ? c - 'p' : c - '0');
        }
        return s.charAt(s.length() - 1) >= 'p' ? -v : v;
    }

    private static boolean zonedNegZero(String s) {
        return s.charAt(s.length() - 1) >= 'p' && zonedValue(s) == 0;
    }

    private static String zoned(long v, boolean negZero, int n) {
        String d = num(v, n);
        if (v < 0 || negZero) {
            return d.substring(0, n - 1) + (char) ('p' + (d.charAt(n - 1) - '0'));
        }
        return d;
    }

    /** GnuCOBOL LINE SEQUENTIAL READ (see Grades.lineSeqRecords for the rules). */
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
                    pos++;
                }
            } else if (pos < n && all.charAt(pos) == '\n') {
                pos++;
            } else if (pos >= n) {
                pos = n - 1;
            }
            recs.add(pad(rec, recLen));
        }
        return recs;
    }

    private static String spaces(int n) {
        return " ".repeat(n);
    }

    private static String pad(String s, int n) {
        return s.length() >= n ? s.substring(0, n) : s + spaces(n - s.length());
    }

    private static String num(long v, int digits) {
        StringBuilder s = new StringBuilder(Long.toString(v < 0 ? -v : v));
        while (s.length() < digits) {
            s.insert(0, '0');
        }
        return s.toString();
    }
}
