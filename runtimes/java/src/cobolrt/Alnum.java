package cobolrt;

/**
 * Alphanumeric semantics on fixed-length {@code byte[]} (ISO-8859-1): MOVE with space padding /
 * right truncation, JUSTIFIED RIGHT, comparison with space padding, reference modification.
 * Static, loop-based, no JDK calls (JBMC-friendly), annotated with JML.
 */
public final class Alnum {
    private Alnum() {}

    public static final byte SPACE = (byte) ' ';

    /** MOVE src TO dst (dst = PIC X(dst.length)): left-aligned, space padded, truncated on the right. */
    /*@ public normal_behavior
      @   requires src != null && dst != null && src != dst;
      @   assignable dst[*];
      @   ensures (\forall int i; 0 <= i && i < dst.length && i < src.length; dst[i] == src[i]);
      @   ensures (\forall int i; src.length <= i && i < dst.length; dst[i] == SPACE);
      @*/
    public static void move(byte[] src, byte[] dst) {
        int n = src.length < dst.length ? src.length : dst.length;
        /*@ loop_invariant 0 <= i && i <= n;
          @ loop_invariant (\forall int j; 0 <= j && j < i; dst[j] == src[j]);
          @ loop_assigns dst[*];
          @ decreases n - i;
          @*/
        for (int i = 0; i < n; i++) {
            dst[i] = src[i];
        }
        /*@ loop_invariant n <= i && i <= dst.length;
          @ loop_invariant (\forall int j; 0 <= j && j < n; dst[j] == src[j]);
          @ loop_invariant (\forall int j; n <= j && j < i; dst[j] == SPACE);
          @ loop_assigns dst[*];
          @ decreases dst.length - i;
          @*/
        for (int i = n; i < dst.length; i++) {
            dst[i] = SPACE;
        }
    }

    /** MOVE src TO dst JUSTIFIED RIGHT: right-aligned, space padded on the left, truncated on the left. */
    /*@ public normal_behavior
      @   requires src != null && dst != null && src != dst;
      @   assignable dst[*];
      @   ensures src.length >= dst.length ==>
      @           (\forall int i; 0 <= i && i < dst.length; dst[i] == src[src.length - dst.length + i]);
      @   ensures src.length < dst.length ==>
      @           (\forall int i; 0 <= i && i < dst.length - src.length; dst[i] == SPACE);
      @   ensures src.length < dst.length ==>
      @           (\forall int i; dst.length - src.length <= i && i < dst.length; dst[i] == src[i - (dst.length - src.length)]);
      @*/
    public static void moveJustified(byte[] src, byte[] dst) {
        if (src.length >= dst.length) {
            int off = src.length - dst.length;
            /*@ loop_invariant 0 <= i && i <= dst.length;
              @ loop_invariant (\forall int j; 0 <= j && j < i; dst[j] == src[off + j]);
              @ loop_assigns dst[*];
              @ decreases dst.length - i;
              @*/
            for (int i = 0; i < dst.length; i++) {
                dst[i] = src[off + i];
            }
        } else {
            int pad = dst.length - src.length;
            /*@ loop_invariant 0 <= i && i <= pad;
              @ loop_invariant (\forall int j; 0 <= j && j < i; dst[j] == SPACE);
              @ loop_assigns dst[*];
              @ decreases pad - i;
              @*/
            for (int i = 0; i < pad; i++) {
                dst[i] = SPACE;
            }
            /*@ loop_invariant pad <= i && i <= dst.length;
              @ loop_invariant (\forall int j; 0 <= j && j < pad; dst[j] == SPACE);
              @ loop_invariant (\forall int j; pad <= j && j < i; dst[j] == src[j - pad]);
              @ loop_assigns dst[*];
              @ decreases dst.length - i;
              @*/
            for (int i = pad; i < dst.length; i++) {
                dst[i] = src[i - pad];
            }
        }
    }

    /** MOVE honouring the target's JUSTIFIED clause. */
    /*@ public normal_behavior
      @   requires src != null && dst != null && src != dst;
      @   assignable dst[*];
      @*/
    public static void move(byte[] src, byte[] dst, boolean justified) {
        if (justified) {
            moveJustified(src, dst);
        } else {
            move(src, dst);
        }
    }

    /** Fill with one byte (MOVE SPACES / ALL x). */
    /*@ public normal_behavior
      @   requires dst != null;
      @   assignable dst[*];
      @   ensures (\forall int i; 0 <= i && i < dst.length; dst[i] == b);
      @*/
    public static void fill(byte[] dst, byte b) {
        /*@ loop_invariant 0 <= i && i <= dst.length;
          @ loop_invariant (\forall int j; 0 <= j && j < i; dst[j] == b);
          @ loop_assigns dst[*];
          @ decreases dst.length - i;
          @*/
        for (int i = 0; i < dst.length; i++) {
            dst[i] = b;
        }
    }

    /** Byte i of x as an unsigned value, spaces beyond the end (comparison padding). */
    /*@ public normal_behavior
      @   requires x != null && i >= 0;
      @   ensures i < x.length ==> \result == (x[i] & 0xFF);
      @   ensures i >= x.length ==> \result == 32;
      @   ensures 0 <= \result && \result <= 255;
      @ pure
      @*/
    public static int padded(byte[] x, int i) {
        return i < x.length ? (x[i] & 0xFF) : 32;
    }

    /** Alphanumeric comparison: the shorter operand is padded with spaces; native byte order. */
    /*@ public normal_behavior
      @   requires a != null && b != null;
      @   ensures \result == -1 || \result == 0 || \result == 1;
      @   ensures \result == 0 <==> (\forall int i; 0 <= i && i < (a.length > b.length ? a.length : b.length);
      @                                 padded(a, i) == padded(b, i));
      @ pure
      @*/
    public static int compare(byte[] a, byte[] b) {
        int n = a.length > b.length ? a.length : b.length;
        /*@ loop_invariant 0 <= i && i <= n;
          @ loop_invariant (\forall int j; 0 <= j && j < i; padded(a, j) == padded(b, j));
          @ decreases n - i;
          @*/
        for (int i = 0; i < n; i++) {
            int x = padded(a, i);
            int y = padded(b, i);
            if (x != y) {
                return x < y ? -1 : 1;
            }
        }
        return 0;
    }

    /** Reference modification item(start:len) with a 1-based start, as a new array. */
    /*@ public normal_behavior
      @   requires data != null && 1 <= start && 1 <= len && start - 1 + len <= data.length;
      @   ensures \result != null && \result.length == len && \fresh(\result);
      @   ensures (\forall int i; 0 <= i && i < len; \result[i] == data[start - 1 + i]);
      @*/
    public static byte[] refmod(byte[] data, int start, int len) {
        byte[] r = new byte[len];
        /*@ loop_invariant 0 <= i && i <= len;
          @ loop_invariant (\forall int j; 0 <= j && j < i; r[j] == data[start - 1 + j]);
          @ loop_assigns r[*];
          @ decreases len - i;
          @*/
        for (int i = 0; i < len; i++) {
            r[i] = data[start - 1 + i];
        }
        return r;
    }

    /** MOVE value TO data(start:len): the slice is treated as PIC X(len). */
    /*@ public normal_behavior
      @   requires data != null && value != null && data != value;
      @   requires 1 <= start && 1 <= len && start - 1 + len <= data.length;
      @   assignable data[*];
      @   ensures (\forall int i; 0 <= i && i < start - 1; data[i] == \old(data[i]));
      @   ensures (\forall int i; start - 1 + len <= i && i < data.length; data[i] == \old(data[i]));
      @   ensures (\forall int i; 0 <= i && i < len && i < value.length; data[start - 1 + i] == value[i]);
      @   ensures (\forall int i; value.length <= i && i < len; data[start - 1 + i] == SPACE);
      @*/
    public static void setRefmod(byte[] data, int start, int len, byte[] value) {
        /*@ loop_invariant 0 <= i && i <= len;
          @ loop_invariant (\forall int j; 0 <= j && j < i && j < value.length; data[start - 1 + j] == value[j]);
          @ loop_invariant (\forall int j; value.length <= j && j < i; data[start - 1 + j] == SPACE);
          @ loop_invariant (\forall int j; 0 <= j && j < start - 1; data[j] == \old(data[j]));
          @ loop_invariant (\forall int j; start - 1 + len <= j && j < data.length; data[j] == \old(data[j]));
          @ loop_assigns data[*];
          @ decreases len - i;
          @*/
        for (int i = 0; i < len; i++) {
            data[start - 1 + i] = i < value.length ? value[i] : SPACE;
        }
    }

    // ---------------------------------------------------------------------------------------------
    // helpers outside the verified core (allocation, Strings)
    // ---------------------------------------------------------------------------------------------

    /** ISO-8859-1 bytes of a Java string. */
    public static byte[] bytes(String s) {
        byte[] b = new byte[s.length()];
        for (int i = 0; i < b.length; i++) {
            b[i] = (byte) s.charAt(i);
        }
        return b;
    }

    /** ISO-8859-1 string of bytes. */
    public static String string(byte[] b) {
        char[] c = new char[b.length];
        for (int i = 0; i < b.length; i++) {
            c[i] = (char) (b[i] & 0xFF);
        }
        return new String(c);
    }

    static boolean isSpace(int c) {
        return c == ' ' || c == '\t' || c == '\n' || c == 0x0B || c == '\f' || c == '\r';
    }

    /**
     * cob_move_alphanum_to_display: text -> stored digit characters of a DISPLAY item with
     * {@code size} digits and {@code scale}; result[size] holds the sign (-1, 0, +1). Leading white
     * space, one +/-, digits, at most one '.', spaces and ',' are accepted; anything else gives
     * zero. Excess digits are dropped.
     */
    static byte[] deedit(byte[] src, int size, int scale) {
        byte[] data = new byte[size + 1];
        for (int i = 0; i < size; i++) {
            data[i] = '0';
        }
        int e1 = src.length;
        int s1 = 0;
        while (s1 < e1 && isSpace(src[s1] & 0xFF)) {
            s1++;
        }
        int sg = 0;
        if (s1 != e1 && (src[s1] == '+' || src[s1] == '-')) {
            sg = src[s1] == '+' ? 1 : -1;
            s1++;
        }
        int count = 0;
        for (int p = s1; p < e1 && src[p] != '.'; p++) {
            if (src[p] >= '0' && src[p] <= '9') {
                count++;
            }
        }
        int isize = size - scale;
        int s2 = 0;
        if (count < isize) {
            s2 = isize - count;
        } else {
            while (count > isize) {
                while (s1 < e1 && !(src[s1] >= '0' && src[s1] <= '9')) {
                    s1++;
                }
                s1++;
                count--;
            }
        }
        int points = 0;
        while (s1 < e1 && s2 < size) {
            int c = src[s1] & 0xFF;
            if (c >= '0' && c <= '9') {
                data[s2++] = (byte) c;
            } else if (c == '.') {
                points++;
                if (points > 1) {
                    return zero(size);
                }
            } else if (!(isSpace(c) || c == ',')) {
                return zero(size);
            }
            s1++;
        }
        data[size] = (byte) sg;
        return data;
    }

    private static byte[] zero(int size) {
        byte[] d = new byte[size + 1];
        for (int i = 0; i < size; i++) {
            d[i] = '0';
        }
        return d;
    }
}
