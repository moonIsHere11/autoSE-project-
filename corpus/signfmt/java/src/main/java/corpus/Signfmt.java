package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of SIGNFMT. Each signed numeric item is a {@code long} scaled by 10^scale
 * plus a {@code ...NegZero} flag: GnuCOBOL can store a negative zero (ACCEPT "-0", MOVE of a
 * negative value whose kept digits are zero, high-order truncation of a negative COMPUTE
 * result). DISPLAY of the item never shows it, but its raw bytes (REDEFINES / group) do.
 */
public class Signfmt {
    String wsTag = "    ";        // X(4)
    long wsCount = 0;             // 9(2)
    long wsLs;                    // S9(3)V99 SIGN LEADING SEPARATE, scale 2
    boolean wsLsNegZero;
    long wsTs;                    // S9(2)V9 SIGN TRAILING SEPARATE, scale 1
    boolean wsTsNegZero;
    long wsEmb;                   // S9(3)V99 (trailing overpunch)
    boolean wsEmbNegZero;
    long wsLemb;                  // S9(3)V99 SIGN LEADING (leading overpunch)
    boolean wsLembNegZero;
    long wsUns;                   // 9(3)V99
    long wsSmall;                 // S9V9, scale 1
    boolean wsSmallNegZero;
    long wsSum;                   // S9(3)V99 SIGN TRAILING SEPARATE
    boolean wsSumNegZero;
    long wsDiff;                  // S9(2)V99
    boolean wsDiffNegZero;
    long wsTotal = 0;             // S9(4)V99 SIGN LEADING SEPARATE VALUE 0
    long wsOverflows = 0;         // 9(2)
    long wsLastOvf = 0;           // 9(2)
    long wsNegCount = 0;
    long wsZeroCount = 0;
    long wsPosCount = 0;
    String wsETag = "    ";       // X(4)
    long wsELs;                   // S9(3)V99 SIGN LEADING SEPARATE
    boolean wsELsNegZero;
    long wsETs;                   // S9(2)V9 SIGN LEADING (embedded)
    boolean wsETsNegZero;
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();
    private boolean lastNeg;

    public static void main(String[] args) throws IOException {
        Signfmt p = new Signfmt();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        readEntry();
        while (!(wsTag.equals("END ") || wsTag.equals("    ") || wsCount >= 30)) {
            convertEntry();
            showEntry();
            readEntry();
        }
        showSummary();
    }

    void readEntry() throws IOException {
        wsTag = acceptAlnum(4);
        if (!wsTag.equals("END ") && !wsTag.equals("    ")) {
            wsLs = acceptNumeric(6, 3, 2);
            wsLsNegZero = lastNeg && wsLs == 0;
            wsTs = acceptNumeric(4, 2, 1);
            wsTsNegZero = lastNeg && wsTs == 0;
            wsCount = (wsCount + 1) % 100;
        }
    }

    void convertEntry() {
        boolean lsNeg = wsLs < 0 || wsLsNegZero;
        long lsAbs = wsLs < 0 ? -wsLs : wsLs;
        // MOVE: digits are aligned and truncated, the sign of the source is kept
        wsEmb = wsLs;
        wsEmbNegZero = wsLsNegZero;
        wsLemb = wsLs;
        wsLembNegZero = wsLsNegZero;
        wsUns = lsAbs;
        long small = (lsAbs / 10) % 100;
        wsSmall = lsNeg ? -small : small;
        wsSmallNegZero = lsNeg && small == 0;
        // COMPUTE: the result's sign survives high-order truncation (a zero result is positive)
        long sum = wsLs + wsTs * 10;
        long sumDigits = (sum < 0 ? -sum : sum) % 100000;
        wsSum = sum < 0 ? -sumDigits : sumDigits;
        wsSumNegZero = sum < 0 && sumDigits == 0;
        long diff = wsLs - wsTs * 10;
        long diffDigits = (diff < 0 ? -diff : diff) % 10000;
        wsDiff = diff < 0 ? -diffDigits : diffDigits;
        wsDiffNegZero = diff < 0 && diffDigits == 0;
        if (wsLs < 0) {
            wsNegCount = (wsNegCount + 1) % 100;
        } else if (wsLs == 0) {
            wsZeroCount = (wsZeroCount + 1) % 100;
        } else {
            wsPosCount = (wsPosCount + 1) % 100;
        }
        wsETag = wsTag;
        wsELs = wsLs;
        wsELsNegZero = wsLsNegZero;
        wsETs = wsTs;
        wsETsNegZero = wsTsNegZero;
        long total = wsTotal + wsLs;
        if (total > 999999 || total < -999999) {
            // END-ADD closes the nested ADD, so the MOVE is still part of ON SIZE ERROR
            wsOverflows = (wsOverflows + 1) % 100;
            wsLastOvf = wsCount;
        } else {
            wsTotal = total;
        }
    }

    void showEntry() {
        line(digits(wsCount, 2) + " " + wsTag + " LS " + lead(wsLs, 3, 2) + " [" + leadSep(wsLs, wsLsNegZero, 5)
                + "] TS " + trail(wsTs, 2, 1) + " [" + trailSep(wsTs, wsTsNegZero, 3) + "]");
        line("   EMB " + lead(wsEmb, 3, 2) + " [" + overpunchTrailing(wsEmb, wsEmbNegZero, 5) + "] LEMB ["
                + overpunchLeading(wsLemb, wsLembNegZero, 5) + "] UNS " + point(digits(wsUns, 5), 2) + " SMALL "
                + lead(wsSmall, 1, 1) + " [" + overpunchTrailing(wsSmall, wsSmallNegZero, 2) + "]");
        line("   SUM " + trail(wsSum, 3, 2) + " [" + trailSep(wsSum, wsSumNegZero, 5) + "] DIFF "
                + lead(wsDiff, 2, 2) + " [" + overpunchTrailing(wsDiff, wsDiffNegZero, 4) + "] ECHO ["
                + wsETag + leadSep(wsELs, wsELsNegZero, 5) + overpunchLeading(wsETs, wsETsNegZero, 3) + "]");
    }

    void showSummary() {
        line("ENTRIES " + digits(wsCount, 2) + " NEGATIVE " + digits(wsNegCount, 2) + " ZERO "
                + digits(wsZeroCount, 2) + " POSITIVE " + digits(wsPosCount, 2));
        line("TOTAL " + lead(wsTotal, 4, 2) + " OVERFLOWS " + digits(wsOverflows, 2) + " LAST "
                + digits(wsLastOvf, 2));
        returnCode = (int) wsNegCount;
    }

    // ---------------------------------------------------------------- display / raw encodings

    /** DISPLAY of a signed field with a leading sign (separate or embedded): never "-0". */
    private static String lead(long v, int intDigits, int scale) {
        return (v < 0 ? "-" : "+") + point(digits(v, intDigits + scale), scale);
    }

    /** DISPLAY of a SIGN TRAILING SEPARATE field. */
    private static String trail(long v, int intDigits, int scale) {
        return point(digits(v, intDigits + scale), scale) + (v < 0 ? "-" : "+");
    }

    private static String leadSep(long v, boolean negZero, int n) {
        return (v < 0 || negZero ? "-" : "+") + digits(v, n);
    }

    private static String trailSep(long v, boolean negZero, int n) {
        return digits(v, n) + (v < 0 || negZero ? "-" : "+");
    }

    /** Raw bytes of a zoned field with a trailing embedded sign: negative last digit = 'p' + d. */
    private static String overpunchTrailing(long v, boolean negZero, int n) {
        String d = digits(v, n);
        if (v < 0 || negZero) {
            return d.substring(0, n - 1) + (char) ('p' + (d.charAt(n - 1) - '0'));
        }
        return d;
    }

    private static String overpunchLeading(long v, boolean negZero, int n) {
        String d = digits(v, n);
        if (v < 0 || negZero) {
            return (char) ('p' + (d.charAt(0) - '0')) + d.substring(1);
        }
        return d;
    }

    private static String digits(long v, int n) {
        StringBuilder sb = new StringBuilder(Long.toString(v < 0 ? -v : v));
        while (sb.length() < n) {
            sb.insert(0, '0');
        }
        return sb.toString();
    }

    private static String point(String ds, int scale) {
        return ds.substring(0, ds.length() - scale) + "." + ds.substring(ds.length() - scale);
    }

    // ---------------------------------------------------------------- ACCEPT helpers

    private void line(String s) {
        out.append(s).append('\n');
    }

    private String readLine() throws IOException {
        int ch = in.read();
        if (ch < 0) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        while (ch >= 0 && ch != '\n') {
            sb.append((char) ch);
            ch = in.read();
        }
        return sb.toString();
    }

    private String acceptAlnum(int n) throws IOException {
        String s = readLine();
        if (s == null) {
            s = "";
        }
        if (s.length() > n) {
            return s.substring(0, n);
        }
        return s + " ".repeat(n - s.length());
    }

    /** ACCEPT into a signed numeric DISPLAY field; {@link #lastNeg} records a '-' sign (for "-0"). */
    private long acceptNumeric(int window, int intDigits, int scale) throws IOException {
        lastNeg = false;
        String s = readLine();
        if (s == null) {
            return 0;
        }
        String w = s.length() > window ? s.substring(0, window) : s;
        int i = 0;
        int n = w.length();
        while (i < n && w.charAt(i) == ' ') {
            i++;
        }
        boolean neg = false;
        if (i < n && (w.charAt(i) == '+' || w.charAt(i) == '-')) {
            neg = w.charAt(i) == '-';
            i++;
            while (i < n && w.charAt(i) == ' ') {
                i++;
            }
        }
        StringBuilder ip = new StringBuilder();
        StringBuilder fp = new StringBuilder();
        boolean dot = false;
        for (; i < n; i++) {
            char c = w.charAt(i);
            if (c >= '0' && c <= '9') {
                (dot ? fp : ip).append(c);
            } else if (c == '.' && !dot) {
                dot = true;
            } else if (c != ',') {
                break;
            }
        }
        while (i < n && w.charAt(i) == ' ') {
            i++;
        }
        if (i < n || ip.length() + fp.length() == 0) {
            return 0;
        }
        long v = 0;
        String ints = ip.length() > intDigits ? ip.substring(ip.length() - intDigits) : ip.toString();
        for (int k = 0; k < ints.length(); k++) {
            v = v * 10 + (ints.charAt(k) - '0');
        }
        for (int k = 0; k < scale; k++) {
            v = v * 10 + (k < fp.length() ? fp.charAt(k) - '0' : 0);
        }
        lastNeg = neg;
        return neg ? -v : v;
    }
}
