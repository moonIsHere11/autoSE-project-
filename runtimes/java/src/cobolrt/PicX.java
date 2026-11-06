package cobolrt;

/** PIC X(n) [JUSTIFIED RIGHT]: fixed-length bytes (ISO-8859-1), initially spaces. */
public final class PicX {
    public final int length;
    public final boolean justified;
    private final byte[] data;

    public PicX(int length, boolean justified) {
        this.length = length;
        this.justified = justified;
        this.data = new byte[length];
        Alnum.fill(data, Alnum.SPACE);
    }

    public PicX(int length) {
        this(length, false);
    }

    /** With a VALUE clause (a VALUE is not justified, measured). */
    public PicX(int length, boolean justified, String value) {
        this(length, justified);
        Alnum.move(Alnum.bytes(value), data);
    }

    /** The live storage (modifications are visible). */
    public byte[] bytes() {
        return data;
    }

    /** MOVE alphanumeric item TO this. */
    public void move(PicX src) {
        Alnum.move(src.data.clone(), data, justified);
    }

    /** MOVE literal / bytes TO this. */
    public void move(String s) {
        Alnum.move(Alnum.bytes(s), data, justified);
    }

    public void move(byte[] b) {
        Alnum.move(b.clone(), data, justified);
    }

    /**
     * MOVE integer numeric item TO this: its digits without sign; trailing P positions become
     * zeros. An unsigned DISPLAY source at least as long as this item is copied byte-wise from the
     * left, ignoring JUSTIFIED (cobc's copy optimisation, measured).
     */
    public void move(CobolDecimal src) {
        Pic p = src.pic;
        if (p.scale > 0) {
            throw new IllegalArgumentException("MOVE of a non-integer numeric item to alphanumeric");
        }
        long mag = Math.abs(src.unscaled());
        if (p.usage == Usage.DISPLAY && !p.signed && p.digits >= length) {
            byte[] d = digits(mag, p.digits);
            for (int i = 0; i < length; i++) {
                data[i] = d[i];
            }
            return;
        }
        int n = p.usage == Usage.DISPLAY ? p.digits : p.gcDigits();
        int nz = n > 18 ? 18 : n;
        byte[] d = digits(mag % Num.pow10(nz), n);
        int zeros = -p.scale;
        int size1 = d.length;
        if (justified) {
            Alnum.fill(data, Alnum.SPACE);
            int size2 = length;
            if (zeros > 0) {
                int z = Math.min(zeros, size2);
                size2 -= z;
                for (int i = 0; i < z; i++) {
                    data[size2 + i] = '0';
                }
            }
            if (size2 > 0) {
                int diff = size2 - size1;
                if (diff > 0) {
                    for (int i = 0; i < size1; i++) {
                        data[diff + i] = d[i];
                    }
                } else {
                    for (int i = 0; i < size2; i++) {
                        data[i] = d[size1 - size2 + i];
                    }
                }
            }
            return;
        }
        if (length < size1) {
            for (int i = 0; i < length; i++) {
                data[i] = d[i];
            }
            return;
        }
        for (int i = 0; i < size1; i++) {
            data[i] = d[i];
        }
        int rest = length - size1;
        int z = Math.max(0, Math.min(zeros, rest));
        for (int i = 0; i < rest; i++) {
            data[size1 + i] = (byte) (i < z ? '0' : ' ');
        }
    }

    private static byte[] digits(long mag, int n) {
        byte[] d = new byte[n];
        for (int i = n - 1; i >= 0; i--) {
            d[i] = (byte) ('0' + mag % 10);
            mag /= 10;
        }
        return d;
    }

    /** Alphanumeric comparison (space padded). */
    public int compareTo(PicX other) {
        return Alnum.compare(data, other.data);
    }

    public int compareTo(String literal) {
        return Alnum.compare(data, Alnum.bytes(literal));
    }

    /** Reference modification this(start:len), 1-based. */
    public byte[] refmod(int start, int len) {
        return Alnum.refmod(data, start, len);
    }

    /** MOVE value TO this(start:len). */
    public void setRefmod(int start, int len, byte[] value) {
        Alnum.setRefmod(data, start, len, value.clone());
    }

    /** ACCEPT this from a line (without newline); {@code null} = end of input (spaces). */
    public void accept(byte[] line) {
        move(line == null ? new byte[] {' '} : line);
    }

    public void accept(String line) {
        accept(line == null ? null : Alnum.bytes(line));
    }

    public byte[] display() {
        return data.clone();
    }

    @Override
    public String toString() {
        return Alnum.string(data);
    }
}
