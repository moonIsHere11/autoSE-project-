package demo;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/** Hand translation of S1PROG (decimals held as scaled longs). */
public class S1prog {
    long wsA;   // S9(5)V99, scale 2
    long wsB;   // 9(3)
    long wsR;   // S9(5)V99, scale 2
    long wsI;   // 9(2)
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        S1prog p = new S1prog();
        p.mainPara();
        System.out.print(p.out);
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        wsA = accept(wsA, 7, 2, true, 7);
        wsB = accept(wsB, 3, 0, false, 3);
        calcPara();
        for (wsI = 1; wsI <= 2; wsI++) {
            out.append("I=").append(pad(wsI, 2)).append('\n');
        }
        if (wsR > 100 * 100) {
            out.append("BIG\n");
        } else {
            out.append("SMALL\n");
        }
        out.append("R=").append(signed(wsR, 7, 2)).append('\n');
        returnCode = 3;
    }

    void calcPara() {
        // WS-A * 1.5 + WS-B, exact at scale 3, then ROUNDED to scale 2 (half away from zero)
        long exact = wsA * 15 + wsB * 1000;
        long q = exact / 10;
        long r = exact % 10;
        if (Math.abs(r) >= 5) {
            q += exact < 0 ? -1 : 1;
        }
        wsR = q % 10_000_000L; // high-order truncation to 5 integer digits
    }

    void neverPara() {
        out.append("NEVER\n");
    }

    /** ACCEPT into a numeric DISPLAY field: first `window` characters, de-edited, aligned, truncated. */
    private long accept(long current, int digits, int scale, boolean signed, int window) throws IOException {
        String line = in.readLine();
        if (line == null) {
            return current;
        }
        String w = line.length() > window ? line.substring(0, window) : line;
        w = w.trim();
        boolean neg = false;
        if (!w.isEmpty() && (w.charAt(0) == '-' || w.charAt(0) == '+')) {
            neg = w.charAt(0) == '-';
            w = w.substring(1).trim();
        }
        String ip = w;
        String fp = "";
        int dot = w.indexOf('.');
        if (dot >= 0) {
            ip = w.substring(0, dot);
            fp = w.substring(dot + 1);
        }
        if (!(ip + fp).chars().allMatch(Character::isDigit) || fp.indexOf('.') >= 0) {
            return 0;
        }
        StringBuilder frac = new StringBuilder(fp);
        while (frac.length() < scale) {
            frac.append('0');
        }
        String digitsStr = ip + frac.substring(0, scale);
        long v = 0;
        for (int i = 0; i < digitsStr.length(); i++) {
            v = (v * 10 + (digitsStr.charAt(i) - '0')) % pow10(digits);
        }
        return (neg && signed) ? -v : v;
    }

    private static long pow10(int n) {
        long p = 1;
        for (int i = 0; i < n; i++) {
            p *= 10;
        }
        return p;
    }

    private static String pad(long v, int width) {
        StringBuilder s = new StringBuilder(Long.toString(Math.abs(v)));
        while (s.length() < width) {
            s.insert(0, '0');
        }
        return s.toString();
    }

    /** GnuCOBOL DISPLAY of a signed DISPLAY numeric field: sign, digits, decimal point. */
    private static String signed(long v, int digits, int scale) {
        String d = pad(v, digits);
        String body = scale > 0 ? d.substring(0, digits - scale) + "." + d.substring(digits - scale) : d;
        return (v < 0 ? "-" : "+") + body;
    }
}
