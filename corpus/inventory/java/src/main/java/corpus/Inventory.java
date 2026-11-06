package corpus;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/**
 * Hand translation of INVENTORY. Numerics are {@code long}s scaled by 10^scale. Record fields
 * are decoded from / encoded to the exact GnuCOBOL byte layouts: COMP-3 (packed, sign nibble
 * C/D/F), COMP (big-endian two's complement), zoned with ASCII overpunch (negative last digit =
 * 0x70 + d) and SIGN LEADING / TRAILING SEPARATE.
 */
public class Inventory {
    private static final int STK_LEN = 21;

    // FD STOCK-FILE (decoded on READ; validity flags mirror IS NUMERIC)
    String stkItem = "      ";  // X(6)
    long stkQty;                // S9(5) COMP-3
    long stkCost;               // 9(4)V99 COMP-3, scale 2
    long stkReorder;            // S9(4) COMP
    long stkAdj;                // S9(3)
    long stkDisc;               // SV99 SIGN LEADING SEPARATE, scale 2
    private byte[] stkRec = new byte[STK_LEN];

    // FD VALUE-FILE
    String valItem = "      ";  // X(6)
    long valNewQty;             // S9(5) COMP-3
    long valUnit;               // S9(4)V99 COMP-3
    boolean valUnitSignF;       // VAL-UNIT carries the unsigned sign nibble F (see wsUnitSignF)
    long valAmount;             // S9(8)V99 COMP-3
    long valCount;              // 9(4) COMP
    String valFlag = " ";       // X
    long valNet;                // S9(7)V99 SIGN TRAILING SEPARATE (digits)
    boolean valNetNegative;     // sign character of VAL-NET

    // WORKING-STORAGE
    String wsEof = "N";
    String wsValid = " ";
    String wsItem = "      ";
    long wsQty;                 // S9(5) COMP-3
    long wsCost;                // 9(4)V99 COMP-3
    long wsReorder;             // S9(4) COMP
    long wsAdj;                 // S9(3)
    long wsDisc;                // SV99 SIGN LEADING SEPARATE
    long wsUnit;                // S9(4)V99 COMP-3
    // GnuCOBOL's packed-to-packed MOVE from the unsigned WS-COST keeps sign nibble F in the
    // signed WS-UNIT; arithmetic results always get C/D. The nibble is visible in VALUE.DAT.
    boolean wsUnitSignF;
    long wsAmount;              // S9(8)V99 COMP-3
    String wsStatus = " ";      // X
    long wsRecCount = 0;        // 9(4) COMP
    long wsRejectCount = 0;
    long wsNegCount = 0;
    long wsReorderCount = 0;
    long wsTotalValue = 0;      // S9(11)V99 COMP-3
    int returnCode;

    private byte[] stockData;
    private int stockPos;
    private final ByteArrayOutputStream valueFile = new ByteArrayOutputStream();
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Inventory p = new Inventory();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        stockData = Files.readAllBytes(Paths.get("STOCK.DAT"));
        stockPos = 0;
        readStock();
        while (!wsEof.equals("Y")) {
            validateRecord();
            if (wsValid.equals("Y")) {
                valueItem();
            } else {
                rejectItem();
            }
            writeValue();
            readStock();
        }
        Files.write(Paths.get("VALUE.DAT"), valueFile.toByteArray());
        setReturn();
        showTotals();
    }

    void readStock() {
        if (stockPos + STK_LEN > stockData.length) {
            wsEof = "Y";
            return;
        }
        System.arraycopy(stockData, stockPos, stkRec, 0, STK_LEN);
        stockPos += STK_LEN;
        stkItem = new String(stkRec, 0, 6, StandardCharsets.ISO_8859_1);
    }

    void validateRecord() {
        wsValid = "N";
        wsItem = stkItem;
        if (packedIsNumeric(stkRec, 6, 3, true) && packedIsNumeric(stkRec, 9, 4, false)
                && zonedIsNumeric(stkRec, 15, 3) && leadingSeparateIsNumeric(stkRec, 18, 3)) {
            wsValid = "Y";
            stkQty = unpack(stkRec, 6, 3);
            stkCost = unpack(stkRec, 9, 4);
            stkReorder = (short) (((stkRec[13] & 0xFF) << 8) | (stkRec[14] & 0xFF));
            stkAdj = unzone(stkRec, 15, 3);
            stkDisc = (stkRec[18] == '-' ? -1 : 1) * Long.parseLong(ascii(stkRec, 19, 2));
            wsQty = stkQty;
            wsCost = stkCost;
            wsReorder = stkReorder;
            wsAdj = stkAdj;
            wsDisc = stkDisc;
        }
    }

    void valueItem() {
        wsStatus = " ";
        long q = wsQty + wsAdj;
        if (q > 99999 || q < -99999) {
            wsStatus = "O";                         // ON SIZE ERROR: WS-QTY unchanged
        } else {
            wsQty = q;
        }
        long product = wsCost * (100 + wsDisc);     // scale 4, never negative
        long unit = (product + 50) / 100;           // ROUNDED to scale 2
        if (unit > 999999) {
            wsUnit = wsCost;
            wsUnitSignF = true;
            wsStatus = "P";
        } else {
            wsUnit = unit;
            wsUnitSignF = false;
        }
        long amount = wsQty * wsUnit;               // scale 2
        if (amount > 9999999999L || amount < -9999999999L) {
            wsAmount = 0;
            wsStatus = "V";
        } else {
            wsAmount = amount;
        }
        if (wsStatus.charAt(0) != ' ') {
            // already flagged
        } else if (wsQty < 0) {
            wsStatus = "N";
            wsNegCount = (wsNegCount + 1) % 10000;
        } else if (wsQty < wsReorder) {
            wsStatus = "R";
            wsReorderCount = (wsReorderCount + 1) % 10000;
        }
        wsTotalValue = wsTotalValue + wsAmount;
    }

    void rejectItem() {
        wsStatus = "X";
        wsQty = 0;
        wsUnit = 0;
        wsUnitSignF = false;
        wsAmount = 0;
        wsRejectCount = (wsRejectCount + 1) % 10000;
    }

    void writeValue() {
        wsRecCount = (wsRecCount + 1) % 10000;
        valItem = wsItem;
        valNewQty = wsQty;
        valUnit = wsUnit;
        valUnitSignF = wsUnitSignF;
        valAmount = wsAmount;
        valCount = wsRecCount;
        valFlag = wsStatus;
        valNet = (wsAmount < 0 ? -wsAmount : wsAmount) % 1000000000L; // MOVE: high-order truncation
        valNetNegative = wsAmount < 0;                                 // MOVE keeps the source sign
        byte[] rec = new byte[32];
        put(rec, 0, valItem.getBytes(StandardCharsets.ISO_8859_1));
        put(rec, 6, pack(valNewQty, 3, true));
        put(rec, 9, pack(valUnit, 4, !valUnitSignF));
        put(rec, 13, pack(valAmount, 6, true));
        rec[19] = (byte) (valCount >> 8);
        rec[20] = (byte) valCount;
        rec[21] = (byte) valFlag.charAt(0);
        put(rec, 22, (digits(valNet, 9) + (valNetNegative ? "-" : "+")).getBytes(StandardCharsets.ISO_8859_1));
        valueFile.write(rec, 0, rec.length);
        String netShown = withPoint(digits(valNet, 9), 2) + (valNetNegative && valNet != 0 ? "-" : "+");
        line(digits(wsRecCount, 4) + " " + wsItem + " QTY " + signed(wsQty, 5, 0) + " UNIT " + signed(wsUnit, 4, 2)
                + " AMOUNT " + signed(wsAmount, 8, 2) + " [" + wsStatus + "] NET " + netShown);
    }

    void setReturn() {
        if (wsRejectCount > 0) {
            returnCode = 12;
        } else if (wsNegCount > 0) {
            returnCode = 8;
        } else if (wsReorderCount > 0) {
            returnCode = 4;
        } else {
            returnCode = 0;
        }
    }

    void showTotals() {
        line("RECORDS " + digits(wsRecCount, 4) + " REJECTED " + digits(wsRejectCount, 4) + " NEGATIVE "
                + digits(wsNegCount, 4) + " REORDER " + digits(wsReorderCount, 4));
        line("TOTAL VALUE " + signed(wsTotalValue, 11, 2));
    }

    // ---------------------------------------------------------------- record codecs

    private static boolean packedIsNumeric(byte[] b, int off, int len, boolean isSigned) {
        for (int i = 0; i < len; i++) {
            int hi = (b[off + i] >> 4) & 0xF;
            int lo = b[off + i] & 0xF;
            if (hi > 9 || (i < len - 1 && lo > 9)) {
                return false;
            }
        }
        int sign = b[off + len - 1] & 0xF;
        return isSigned ? (sign == 0xC || sign == 0xD) : sign == 0xF;
    }

    private static long unpack(byte[] b, int off, int len) {
        long v = 0;
        for (int i = 0; i < len; i++) {
            int hi = (b[off + i] >> 4) & 0xF;
            int lo = b[off + i] & 0xF;
            v = v * 10 + hi;
            if (i < len - 1) {
                v = v * 10 + lo;
            }
        }
        return (b[off + len - 1] & 0xF) == 0xD ? -v : v;
    }

    private static byte[] pack(long v, int len, boolean isSigned) {
        byte[] r = new byte[len];
        long a = v < 0 ? -v : v;
        int sign = isSigned ? (v < 0 ? 0xD : 0xC) : 0xF;
        int nibbles = len * 2;
        int[] nib = new int[nibbles];
        nib[nibbles - 1] = sign;
        for (int i = nibbles - 2; i >= 0; i--) {
            nib[i] = (int) (a % 10);
            a /= 10;
        }
        for (int i = 0; i < len; i++) {
            r[i] = (byte) ((nib[2 * i] << 4) | nib[2 * i + 1]);
        }
        return r;
    }

    private static boolean zonedIsNumeric(byte[] b, int off, int len) {
        for (int i = 0; i < len - 1; i++) {
            if (b[off + i] < '0' || b[off + i] > '9') {
                return false;
            }
        }
        int last = b[off + len - 1] & 0xFF;
        return (last >= '0' && last <= '9') || (last >= 0x70 && last <= 0x79);
    }

    private static long unzone(byte[] b, int off, int len) {
        long v = 0;
        for (int i = 0; i < len - 1; i++) {
            v = v * 10 + (b[off + i] - '0');
        }
        int last = b[off + len - 1] & 0xFF;
        if (last >= 0x70) {
            return -(v * 10 + (last - 0x70));
        }
        return v * 10 + (last - '0');
    }

    private static boolean leadingSeparateIsNumeric(byte[] b, int off, int len) {
        if (b[off] != '+' && b[off] != '-') {
            return false;
        }
        for (int i = 1; i < len; i++) {
            if (b[off + i] < '0' || b[off + i] > '9') {
                return false;
            }
        }
        return true;
    }

    private static String ascii(byte[] b, int off, int len) {
        return new String(b, off, len, StandardCharsets.ISO_8859_1);
    }

    private static void put(byte[] dst, int off, byte[] src) {
        System.arraycopy(src, 0, dst, off, src.length);
    }

    // ---------------------------------------------------------------- display helpers

    private void line(String s) {
        out.append(s).append('\n');
    }

    private static String digits(long v, int n) {
        StringBuilder sb = new StringBuilder(Long.toString(v < 0 ? -v : v));
        while (sb.length() < n) {
            sb.insert(0, '0');
        }
        return sb.toString();
    }

    private static String withPoint(String ds, int scale) {
        return scale == 0 ? ds : ds.substring(0, ds.length() - scale) + "." + ds.substring(ds.length() - scale);
    }

    private static String signed(long v, int intDigits, int scale) {
        return (v < 0 ? "-" : "+") + withPoint(digits(v, intDigits + scale), scale);
    }
}
