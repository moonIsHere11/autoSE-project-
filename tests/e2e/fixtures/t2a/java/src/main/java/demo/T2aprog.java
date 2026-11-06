package demo;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/** Hand translation of T2APROG (decimals as longs scaled by 10^scale). */
public class T2aprog {
    long wsQty;    // 9(2)
    long wsCode;   // 9
    long wsPrice;  // 9(3)V99, scale 2
    long wsTotal;  // 9(4)V99, scale 2
    long wsDisc;   // 9(3)V99, scale 2
    long wsNet;    // S9(4)V99, scale 2

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        T2aprog p = new T2aprog();
        p.mainPara();
        System.out.print(p.out);
        System.out.flush();
        System.exit(0);
    }

    void mainPara() throws IOException {
        wsQty = acceptUnsignedInt(wsQty, 2);
        wsCode = acceptUnsignedInt(wsCode, 1);
        calcPara();
        out.append("TOTAL=").append(fmt(wsTotal, 6, 2)).append(" NET=")
           .append(wsNet < 0 ? '-' : '+').append(fmt(wsNet < 0 ? -wsNet : wsNet, 6, 2)).append('\n');
    }

    void calcPara() {
        if (wsCode == 0) {
            wsPrice = 125;
        } else if (wsCode >= 1 && wsCode <= 4) {
            wsPrice = 1999;
        } else {
            wsPrice = 750;
        }
        // qty * price(scale 2) * 1.075(scale 3) is exact at scale 5; ROUNDED to scale 2
        long exact = wsQty * wsPrice * 1075;
        wsTotal = ((exact + 500) / 1000) % 1000000;
        if (wsQty > 50) {
            // total(scale 2) * 0.125(scale 3) exact at scale 5; ROUNDED to scale 2
            wsDisc = ((wsTotal * 125 + 500) / 1000) % 100000;
        } else {
            wsDisc = 0;
        }
        wsNet = (wsTotal - wsDisc) % 1000000;
    }

    /** ACCEPT into an unsigned integer DISPLAY field of `width` digits (canonical inputs only). */
    private long acceptUnsignedInt(long current, int width) throws IOException {
        String line = in.readLine();
        if (line == null) {
            return current;
        }
        String w = line.length() > width ? line.substring(0, width) : line;
        long v = 0;
        for (int i = 0; i < w.length(); i++) {
            char c = w.charAt(i);
            if (c < '0' || c > '9') {
                return 0;
            }
            v = v * 10 + (c - '0');
        }
        return v;
    }

    private static String fmt(long v, int digits, int scale) {
        StringBuilder s = new StringBuilder(Long.toString(v));
        while (s.length() < digits) {
            s.insert(0, '0');
        }
        return s.substring(0, digits - scale) + "." + s.substring(digits - scale);
    }
}
