import cobolrt.*;

import java.io.*;
import java.nio.file.*;
import java.util.*;

/**
 * Difftest driver: interprets each batch's script.txt with the Java cobolrt (object API) and
 * writes java.out / java.enc next to it. For arithmetic and MOVE cases whose operands fit in 63
 * bits it also recomputes the result with the static core {@link Num} and prints a CORE-MISMATCH
 * line if the two disagree (so the core is validated against GnuCOBOL too). Core check counts go
 * to /w/java_core.txt.
 */
public class Driver {
    static int coreChecks = 0;
    static int coreSkipped = 0;

    public static void main(String[] args) throws Exception {
        for (String dir : args) {
            Path d = Paths.get(dir);
            List<String> lines = Files.readAllLines(d.resolve("script.txt"));
            byte[] stdin = Files.readAllBytes(d.resolve("stdin.txt"));
            Accept acc = new Accept(new ByteArrayInputStream(stdin));
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            ByteArrayOutputStream enc = new ByteArrayOutputStream();
            for (String line : lines) {
                if (!line.trim().isEmpty()) {
                    runCase(line, acc, out, enc);
                }
            }
            Files.write(d.resolve("java.out"), out.toByteArray());
            Files.write(d.resolve("java.enc"), enc.toByteArray());
        }
        Files.write(Paths.get("/w/java_core.txt"),
                ("core_checks=" + coreChecks + " core_skipped=" + coreSkipped + "\n").getBytes());
    }

    static Object parseField(String spec) {
        String[] p = spec.split(",", -1);
        if (p[0].equals("N")) {
            Pic pic = new Pic(Integer.parseInt(p[1]), Integer.parseInt(p[2]), p[3].equals("1"),
                    Integer.parseInt(p[4]), p[5].equals("1"), p[6].equals("1"));
            CobolDecimal c = new CobolDecimal(pic);
            c.move(p[7]);
            return c;
        }
        PicX x = new PicX(Integer.parseInt(p[1]), p[2].equals("1"));
        x.move(p[3].equals("-") ? new byte[0] : hex(p[3]));
        return x;
    }

    static byte[] hex(String h) {
        byte[] b = new byte[h.length() / 2];
        for (int i = 0; i < b.length; i++) {
            b[i] = (byte) Integer.parseInt(h.substring(2 * i, 2 * i + 2), 16);
        }
        return b;
    }

    static String hexOf(byte[] b) {
        StringBuilder s = new StringBuilder();
        for (byte x : b) {
            s.append(String.format("%02X", x & 0xFF));
        }
        return s.toString();
    }

    static void show(ByteArrayOutputStream out, String cid, String tag, Object item) throws IOException {
        byte[] disp = item instanceof CobolDecimal ? ((CobolDecimal) item).display() : ((PicX) item).display();
        byte[] raw = item instanceof CobolDecimal ? ((CobolDecimal) item).encode() : ((PicX) item).bytes();
        out.write(("#" + cid + " " + tag + " ").getBytes("ISO-8859-1"));
        out.write(disp);
        out.write(("|" + hexOf(raw) + "\n").getBytes("ISO-8859-1"));
    }

    static void line(ByteArrayOutputStream out, String s) throws IOException {
        out.write((s + "\n").getBytes("ISO-8859-1"));
    }

    static int sizeCode(int sc) {
        return sc == 0 ? SizeError.NONE : sc == 2 ? SizeError.NOT_ONLY : SizeError.ON;
    }

    static Dec rpn(String[] toks, List<Object> items) {
        Deque<Dec> st = new ArrayDeque<>();
        for (String t : toks) {
            if (t.startsWith("$")) {
                st.push(((CobolDecimal) items.get(Integer.parseInt(t.substring(1)))).dec());
            } else if (t.startsWith("#")) {
                st.push(Dec.literal(t.substring(1)));
            } else if (t.equals("~")) {
                st.push(st.pop().negate());
            } else {
                Dec b = st.pop();
                Dec a = st.pop();
                switch (t) {
                    case "+": st.push(a.add(b)); break;
                    case "-": st.push(a.subtract(b)); break;
                    case "*": st.push(a.multiply(b)); break;
                    default: st.push(a.divide(b)); break;
                }
            }
        }
        return st.pop();
    }

    static void runCase(String line, Accept acc, ByteArrayOutputStream out, ByteArrayOutputStream enc)
            throws IOException {
        String head = line;
        String[] extra = new String[0];
        int k = line.indexOf(" -- ");
        if (k >= 0) {
            head = line.substring(0, k);
            extra = line.substring(k + 4).trim().split(" ");
        }
        String[] t = head.split(" ");
        String cid = t[0];
        String op = t[1];
        int rnd = Integer.parseInt(t[2]);
        int sc = Integer.parseInt(t[3]);
        int size = sizeCode(sc);
        List<Object> items = new ArrayList<>();
        for (int i = 4; i < t.length; i++) {
            items.add(parseField(t[i]));
        }
        Boolean err = null;
        switch (op) {
            case "MOVE": {
                CobolDecimal a = (CobolDecimal) items.get(0);
                CobolDecimal b = (CobolDecimal) items.get(1);
                if (items.get(1) instanceof CobolDecimal) {
                    coreMove(cid, a, b, out);
                }
                b.move(a);
                show(out, cid, "R1", b);
                break;
            }
            case "MOVEL": {
                CobolDecimal a = (CobolDecimal) items.get(0);
                a.move(extra[0]);
                show(out, cid, "R1", a);
                break;
            }
            case "DISP":
                show(out, cid, "R1", items.get(0));
                break;
            case "ENC": {
                CobolDecimal a = (CobolDecimal) items.get(0);
                byte[] e = a.encode();
                enc.write(e);
                for (int i = e.length; i < 40; i++) {
                    enc.write('*');
                }
                show(out, cid, "R1", a);
                break;
            }
            case "ADD": case "SUB": case "MUL": case "DIVI": {
                CobolDecimal a = (CobolDecimal) items.get(0);
                CobolDecimal b = (CobolDecimal) items.get(1);
                long before = b.unscaled();
                Pic bp = b.pic;
                if (op.equals("ADD")) {
                    err = b.add(a, rnd, size);
                } else if (op.equals("SUB")) {
                    err = b.subtract(a, rnd, size);
                } else if (op.equals("MUL")) {
                    err = b.multiply(a, rnd, size);
                } else {
                    err = b.divide(a, rnd, size);
                }
                status(out, cid, err, sc);
                show(out, cid, "R1", b);
                break;
            }
            case "ADDG": case "SUBG": case "MULG": case "DIVIG": case "DIVBG": {
                CobolDecimal a = (CobolDecimal) items.get(0);
                CobolDecimal b = (CobolDecimal) items.get(1);
                CobolDecimal c = (CobolDecimal) items.get(2);
                Dec v;
                switch (op) {
                    case "ADDG": v = a.dec().add(b.dec()); break;
                    case "SUBG": v = b.dec().subtract(a.dec()); break;
                    case "MULG": v = a.dec().multiply(b.dec()); break;
                    case "DIVIG": v = b.dec().divide(a.dec()); break;
                    default: v = a.dec().divide(b.dec()); break;
                }
                long cBefore = c.unscaled();
                err = c.compute(v, rnd, size);
                coreGiving(cid, op, a, b, c, cBefore, rnd, size, err, out);
                status(out, cid, err, sc);
                show(out, cid, "R1", c);
                break;
            }
            case "DIVBR": case "DIVIR": {
                CobolDecimal a = (CobolDecimal) items.get(0);
                CobolDecimal b = (CobolDecimal) items.get(1);
                CobolDecimal q = (CobolDecimal) items.get(2);
                CobolDecimal r = (CobolDecimal) items.get(3);
                CobolDecimal dividend = op.equals("DIVBR") ? a : b;
                CobolDecimal divisor = op.equals("DIVBR") ? b : a;
                long rBefore = r.unscaled();
                err = CobolDecimal.divideRemainder(dividend, divisor, q, r, rnd, size);
                coreRemainder(cid, dividend, divisor, q, r, rBefore, size, out);
                status(out, cid, err, sc);
                show(out, cid, "R1", q);
                show(out, cid, "R2", r);
                break;
            }
            case "COMP": {
                CobolDecimal tg = (CobolDecimal) items.get(0);
                err = tg.compute(rpn(extra, items), rnd, size);
                status(out, cid, err, sc);
                show(out, cid, "R1", tg);
                break;
            }
            case "NX":
                ((PicX) items.get(1)).move((CobolDecimal) items.get(0));
                show(out, cid, "R1", items.get(1));
                break;
            case "XN":
                ((CobolDecimal) items.get(1)).move((PicX) items.get(0));
                show(out, cid, "R1", items.get(1));
                break;
            case "XX":
                ((PicX) items.get(1)).move((PicX) items.get(0));
                show(out, cid, "R1", items.get(1));
                break;
            case "XL":
                ((PicX) items.get(0)).move(hex(extra[0]));
                show(out, cid, "R1", items.get(0));
                break;
            case "CMP": case "XCMP": {
                int c = op.equals("CMP")
                        ? ((CobolDecimal) items.get(0)).compareTo((CobolDecimal) items.get(1))
                        : ((PicX) items.get(0)).compareTo((PicX) items.get(1));
                line(out, "#" + cid + " " + (c < 0 ? "LT" : c == 0 ? "EQ" : "GT"));
                break;
            }
            case "ACC":
                acc.into((CobolDecimal) items.get(0));
                show(out, cid, "R1", items.get(0));
                break;
            case "ACCX":
                acc.into((PicX) items.get(0));
                show(out, cid, "R1", items.get(0));
                break;
            default:
                throw new IllegalArgumentException(op);
        }
    }

    static void status(ByteArrayOutputStream out, String cid, boolean err, int sc) throws IOException {
        if (err && (sc == 1 || sc == 3)) {
            line(out, "#" + cid + " SE");
        }
        if (!err && (sc == 1 || sc == 2)) {
            line(out, "#" + cid + " NSE");
        }
    }

    // ---- static core cross-checks ----------------------------------------------------------------

    static boolean small(CobolDecimal x) {
        return !x.pic.isU64() && Math.abs(x.pic.scale) <= 18;
    }

    static void mismatch(ByteArrayOutputStream out, String cid, String what) throws IOException {
        line(out, "#" + cid + " CORE-MISMATCH " + what);
    }

    static void coreMove(String cid, CobolDecimal a, CobolDecimal b, ByteArrayOutputStream out) throws IOException {
        Pic s = a.pic;
        Pic d = b.pic;
        if (!small(a) || !small(b) || d.usage == Usage.COMP3 && (s.usage == Usage.COMP3 || s.isBinary())
                || s.equals(d) || d.scale - s.scale > 18
                || (d.scale > s.scale && !Num.fitsShiftUp(a.unscaled(), d.scale - s.scale))) {
            coreSkipped++;
            return;
        }
        coreChecks++;
        long v = Num.move(a.unscaled(), s.scale, d.digits, d.scale, d.signed, d.usage);
        boolean nz = Num.moveNegativeZero(a.unscaled(), a.isNegativeZero(), s.isBinary(), s.scale,
                d.digits, d.scale, d.signed, d.usage);
        CobolDecimal ref = new CobolDecimal(d);
        ref.move(a);
        if (v != ref.unscaled() || nz != ref.isNegativeZero()) {
            mismatch(out, cid, "move " + v + " " + nz);
        }
    }

    /** Store an exact long intermediate with the static core, as generated reference code would. */
    static Long coreStore(long v, int vscale, Pic p, long before, int mode, int size) {
        if (p.scale - vscale > 18 || vscale - p.scale > 1000
                || (p.scale > vscale && !Num.fitsShiftUp(v, p.scale - vscale))) {
            return null;
        }
        boolean keep = p.usage == Usage.COMP5 ? size == SizeError.ON : size != SizeError.NONE;
        boolean se = Num.sizeError(v, vscale, p.digits, p.scale, p.signed, p.usage, mode);
        if (mode == Round.PROHIBITED && Num.prohibitedError(v, vscale, p.scale)) {
            return before;
        }
        if (se && keep) {
            return before;
        }
        return Num.store(v, vscale, p.digits, p.scale, p.signed, p.usage, mode);
    }

    static void coreGiving(String cid, String op, CobolDecimal a, CobolDecimal b, CobolDecimal c, long before,
                           int mode, int size, boolean err, ByteArrayOutputStream out) throws IOException {
        if (!small(a) || !small(b) || !small(c)) {
            coreSkipped++;
            return;
        }
        long x = a.unscaled();
        long y = b.unscaled();
        int sx = a.pic.scale;
        int sy = b.pic.scale;
        Long res;
        Pic p = c.pic;
        if (op.equals("ADDG") || op.equals("SUBG")) {
            int s = Math.max(sx, sy);
            if (!Num.fitsShiftUp(x, s - sx) || !Num.fitsShiftUp(y, s - sy)) {
                coreSkipped++;
                return;
            }
            long v = op.equals("ADDG") ? Num.shiftUp(x, s - sx) + Num.shiftUp(y, s - sy)
                    : Num.shiftUp(y, s - sy) - Num.shiftUp(x, s - sx);
            res = coreStore(v, s, p, before, mode, size);
        } else if (op.equals("MULG")) {
            if (!Num.fitsMul(x, y)) {
                coreSkipped++;
                return;
            }
            res = coreStore(x * y, sx + sy, p, before, mode, size);
        } else {
            long num = op.equals("DIVBG") ? x : y;
            long den = op.equals("DIVBG") ? y : x;
            int sn = op.equals("DIVBG") ? sx : sy;
            int sd = op.equals("DIVBG") ? sy : sx;
            int kk = p.scale + 1 - sn + sd;
            if (den == 0 || kk > 18 || kk < -18 || (kk >= 0 && !Num.fitsShiftUp(num, kk))
                    || (kk < 0 && !Num.fitsShiftUp(den, -kk))) {
                coreSkipped++;
                return;
            }
            boolean keep = p.usage == Usage.COMP5 ? size == SizeError.ON : size != SizeError.NONE;
            if (mode == Round.PROHIBITED && Num.divideProhibitedError(num)) {
                res = before;
            } else {
                long q = Num.divide(num, sn, den, sd, p.scale, mode);
                boolean se = Num.overflows(p.signed ? q : Num.abs(q), p.digits, p.signed, p.usage, p.byteLength());
                res = se && keep ? before : Num.storeValue(q, p.digits, p.signed, p.usage, p.byteLength());
            }
        }
        if (res == null) {
            coreSkipped++;
            return;
        }
        coreChecks++;
        if (res != c.unscaled()) {
            mismatch(out, cid, op + " core=" + res + " obj=" + c.unscaled());
        }
    }

    static void coreRemainder(String cid, CobolDecimal dividend, CobolDecimal divisor, CobolDecimal q,
                              CobolDecimal r, long rBefore, int size, ByteArrayOutputStream out)
            throws IOException {
        if (!small(dividend) || !small(divisor) || !small(q) || !small(r) || divisor.unscaled() == 0) {
            coreSkipped++;
            return;
        }
        long a = dividend.unscaled();
        long b = divisor.unscaled();
        int sa = dividend.pic.scale;
        int sb = divisor.pic.scale;
        int qs = q.pic.scale;
        int kk = qs + 1 - sa + sb;
        int rs = Num.remainderScale(sa, sb, qs);
        if (kk > 18 || kk < -18 || (kk >= 0 && !Num.fitsShiftUp(a, kk)) || (kk < 0 && !Num.fitsShiftUp(b, -kk))
                || rs - sa > 18 || rs - qs - sb > 18 || !Num.fitsShiftUp(a, rs - sa)) {
            coreSkipped++;
            return;
        }
        long qt = Num.divide(a, sa, b, sb, qs, Round.TRUNCATION);
        if (!Num.fitsMul(qt, b) || !Num.fitsShiftUp(qt * b, rs - qs - sb)) {
            coreSkipped++;
            return;
        }
        long rem = Num.remainder(a, sa, b, sb, qs);
        Long res = coreStore(rem, rs, r.pic, rBefore, Round.TRUNCATION, size);
        if (res == null) {
            coreSkipped++;
            return;
        }
        coreChecks++;
        if (res != r.unscaled()) {
            mismatch(out, cid, "remainder core=" + res + " obj=" + r.unscaled());
        }
    }
}
