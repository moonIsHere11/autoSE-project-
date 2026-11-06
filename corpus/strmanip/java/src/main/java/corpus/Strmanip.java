package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of STRMANIP. PIC X items are Java Strings kept at exactly their PIC length
 * (space padded); STRING / UNSTRING / INSPECT are reproduced with explicit loops.
 */
public class Strmanip {
    String wsLine = spaces(20);        // X(20)
    long wsCount = 0;                  // 9(2)
    String wsUpper = spaces(20);       // X(20)
    long wsSpaces;                     // 9(2)
    long wsVowels;                     // 9(2)
    long wsDigitCount;                 // 9(2)
    long wsLen;                        // 9(2)
    String wsReversed = spaces(20);    // X(20)
    long wsI;                          // 9(2)
    long wsJ;                          // 9(2)
    String wsShort = spaces(8);        // X(8)
    String wsRight = spaces(12);       // X(12) JUSTIFIED RIGHT
    String wsFirstWord = spaces(10);   // X(10)
    String wsSecondWord = spaces(10);  // X(10)
    String wsOut = spaces(40);         // X(40)
    long wsPtr;                        // 9(2)
    String wsOverflow = " ";           // X
    String wsMasked = spaces(20);      // X(20)
    long wsTotalVowels = 0;            // 9(3)
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Strmanip p = new Strmanip();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        getLine();
        while (!(isLineEnd() || wsLine.equals(spaces(20)) || wsCount >= 20)) {
            analyseLine();
            buildOutput();
            showLine();
            getLine();
        }
        line("LINES " + num(wsCount, 2) + " VOWELS " + num(wsTotalVowels, 3));
    }

    private boolean isLineEnd() {
        return wsLine.equals(pad("END", 20));
    }

    void getLine() throws IOException {
        String s = readLine();
        wsLine = pad(s == null ? "" : s, 20);
        if (!isLineEnd() && !wsLine.equals(spaces(20))) {
            wsCount = (wsCount + 1) % 100;
        }
    }

    void analyseLine() {
        StringBuilder up = new StringBuilder(wsLine);
        for (int k = 0; k < up.length(); k++) {
            char c = up.charAt(k);
            if (c >= 'a' && c <= 'z') {
                up.setCharAt(k, (char) (c - 'a' + 'A'));
            }
        }
        wsUpper = up.toString();
        wsSpaces = 0;
        wsVowels = 0;
        wsDigitCount = 0;
        for (int k = 0; k < 20; k++) {
            char c = wsLine.charAt(k);
            if (c == ' ') {
                wsSpaces++;
            }
            if (c >= '0' && c <= '9') {
                wsDigitCount++;
            }
            char u = wsUpper.charAt(k);
            if (u == 'A' || u == 'E' || u == 'I' || u == 'O' || u == 'U') {
                wsVowels++;
            }
        }
        wsTotalVowels = (wsTotalVowels + wsVowels) % 1000;
        wsLen = 20;
        while (!(wsLen == 0 || wsLine.charAt((int) wsLen - 1) != ' ')) {
            wsLen--;
        }
        StringBuilder rev = new StringBuilder(spaces(20));
        for (wsI = 1; wsI <= wsLen; wsI++) {
            wsJ = wsLen - wsI + 1;
            rev.setCharAt((int) wsI - 1, wsLine.charAt((int) wsJ - 1));
        }
        wsReversed = rev.toString();
    }

    void buildOutput() {
        wsShort = wsLine.substring(0, 8);
        String src = wsLine.substring(0, (int) wsLen);
        wsRight = src.length() >= 12 ? src.substring(src.length() - 12) : spaces(12 - src.length()) + src;
        wsFirstWord = spaces(10);
        wsSecondWord = spaces(10);
        unstringAllSpace();
        wsOut = spaces(40);
        wsOverflow = "N";
        wsPtr = 1;
        StringBuilder o = new StringBuilder(wsOut);
        boolean ok = stringInto(o, delimited(wsFirstWord, " "))
                && stringInto(o, "/")
                && stringInto(o, wsUpper.substring(0, (int) wsLen))
                && stringInto(o, "/")
                && stringInto(o, delimited(wsReversed, "  "));
        wsOut = o.toString();
        if (!ok) {
            wsOverflow = "Y";
        }
        StringBuilder m = new StringBuilder(wsLine);
        for (int k = 0; k < 20; k++) {
            char c = m.charAt(k);
            if (c == 'a') {
                m.setCharAt(k, '4');
            } else if (c == 'e') {
                m.setCharAt(k, '3');
            } else if (c == 'o') {
                m.setCharAt(k, '0');
            }
        }
        for (int k = 0; k < 20 && m.charAt(k) == ' '; k++) {
            m.setCharAt(k, '.');
        }
        wsMasked = m.toString();
    }

    void showLine() {
        line(num(wsCount, 2) + " [" + wsLine + "] LEN " + num(wsLen, 2) + " SP " + num(wsSpaces, 2) + " VOW "
                + num(wsVowels, 2) + " DIG " + num(wsDigitCount, 2));
        line("   UP [" + wsUpper + "] REV [" + wsReversed + "]");
        line("   SHORT [" + wsShort + "] RIGHT [" + wsRight + "] WORDS [" + wsFirstWord + "] [" + wsSecondWord + "]");
        line("   OUT [" + wsOut + "] PTR " + num(wsPtr, 2) + " OVF " + wsOverflow + " MASK [" + wsMasked + "]");
    }

    // ---------------------------------------------------------------- STRING / UNSTRING helpers

    /** UNSTRING WS-LINE DELIMITED BY ALL SPACE INTO WS-FIRST-WORD WS-SECOND-WORD. */
    private void unstringAllSpace() {
        int pos = 0;
        for (int field = 0; field < 2 && pos < 20; field++) {
            int end = wsLine.indexOf(' ', pos);
            if (end < 0) {
                end = 20;
            }
            String part = pad(wsLine.substring(pos, end), 10);
            if (field == 0) {
                wsFirstWord = part;
            } else {
                wsSecondWord = part;
            }
            pos = end;
            while (pos < 20 && wsLine.charAt(pos) == ' ') {
                pos++;
            }
        }
    }

    /** The part of {@code s} before the first occurrence of {@code delim}. */
    private static String delimited(String s, String delim) {
        int k = s.indexOf(delim);
        return k < 0 ? s : s.substring(0, k);
    }

    /** STRING ... INTO WS-OUT WITH POINTER WS-PTR: false on overflow (pointer past the end). */
    private boolean stringInto(StringBuilder o, String s) {
        for (int k = 0; k < s.length(); k++) {
            if (wsPtr < 1 || wsPtr > o.length()) {
                return false;
            }
            o.setCharAt((int) wsPtr - 1, s.charAt(k));
            wsPtr++;
        }
        return true;
    }

    // ---------------------------------------------------------------- I/O helpers

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

    private static String spaces(int n) {
        return " ".repeat(n);
    }

    private static String pad(String s, int n) {
        return s.length() >= n ? s.substring(0, n) : s + spaces(n - s.length());
    }

    private static String num(long v, int digits) {
        StringBuilder s = new StringBuilder(Long.toString(v));
        while (s.length() < digits) {
            s.insert(0, '0');
        }
        return s.toString();
    }
}
