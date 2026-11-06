package cobolrt;

/**
 * Description of a numeric elementary item.
 *
 * <p>{@code digits} counts the digit positions that are stored (the 9s; P positions are not
 * stored), {@code scale} is the power of ten the stored integer is divided by:
 * {@code 9(3)V99} = (5, 2), {@code 9(3)PP} = (3, -2), {@code PP99} = (2, 4).
 */
public final class Pic {
    public final int digits;
    public final int scale;
    public final boolean signed;
    public final int usage;
    public final boolean signLeading;
    public final boolean signSeparate;

    public Pic(int digits, int scale, boolean signed, int usage, boolean signLeading, boolean signSeparate) {
        if (digits < 1 || digits > 18) {
            throw new IllegalArgumentException("digits must be 1..18");
        }
        if ((signLeading || signSeparate) && (!signed || usage != Usage.DISPLAY)) {
            throw new IllegalArgumentException("SIGN LEADING/SEPARATE needs a signed DISPLAY item");
        }
        this.digits = digits;
        this.scale = scale;
        this.signed = signed;
        this.usage = usage;
        this.signLeading = signLeading;
        this.signSeparate = signSeparate;
    }

    public Pic(int digits, int scale, boolean signed, int usage) {
        this(digits, scale, signed, usage, false, false);
    }

    /** binary-size 1-2-4-8. */
    /*@ public normal_behavior
      @   ensures \result == (digits <= 2 ? 1 : digits <= 4 ? 2 : digits <= 9 ? 4 : 8);
      @   ensures \result == 1 || \result == 2 || \result == 4 || \result == 8;
      @ pure
      @*/
    public static int binaryBytes(int digits) {
        return digits <= 2 ? 1 : digits <= 4 ? 2 : digits <= 9 ? 4 : 8;
    }

    public int byteLength() {
        if (usage == Usage.DISPLAY) {
            return digits + (signSeparate ? 1 : 0);
        }
        if (usage == Usage.COMP3) {
            return digits / 2 + 1;
        }
        return binaryBytes(digits);
    }

    public boolean isBinary() {
        return usage == Usage.COMP || usage == Usage.COMP5;
    }

    /** GnuCOBOL's digit count (P positions after the 9s are counted). */
    public int gcDigits() {
        return scale < 0 ? digits - scale : digits;
    }

    /** An unsigned 8-byte COMP-5 item: its value is the unsigned 64-bit reading of the long. */
    public boolean isU64() {
        return usage == Usage.COMP5 && !signed && byteLength() == 8;
    }

    /**
     * Parse a PICTURE such as {@code S9(5)V99}, {@code 9(3)PP}, {@code PP99} with a USAGE
     * ({@code ""}/DISPLAY, COMP, COMP-4, BINARY, COMP-3, PACKED-DECIMAL, COMP-5) and a SIGN clause
     * ({@code ""}, {@code "LEADING"}, {@code "TRAILING SEPARATE"}, ...).
     */
    public static Pic parse(String picture, String usage, String sign) {
        String t = picture.toUpperCase().replace(" ", "");
        boolean sg = false;
        boolean seenV = false;
        boolean seen9 = false;
        boolean leadingP = false;
        int d = 0;
        int s = 0;
        int i = 0;
        while (i < t.length()) {
            char c = t.charAt(i++);
            int n = 1;
            if (i < t.length() && t.charAt(i) == '(') {
                int j = t.indexOf(')', i);
                n = Integer.parseInt(t.substring(i + 1, j));
                i = j + 1;
            }
            if (c == 'S') {
                sg = true;
            } else if (c == 'V') {
                seenV = true;
            } else if (c == '9') {
                d += n;
                if (seenV || leadingP) {
                    s += n;
                }
                seen9 = true;
            } else if (c == 'P') {
                if (seenV || !seen9) {
                    s += n;
                    leadingP = true;
                } else {
                    s -= n;
                }
            } else {
                throw new IllegalArgumentException("unsupported PICTURE " + picture);
            }
        }
        String u = usage == null ? "" : usage.toUpperCase().replace("COMPUTATIONAL", "COMP").trim();
        int us;
        if (u.isEmpty() || u.equals("DISPLAY")) {
            us = Usage.DISPLAY;
        } else if (u.equals("COMP") || u.equals("COMP-4") || u.equals("BINARY")) {
            us = Usage.COMP;
        } else if (u.equals("COMP-3") || u.equals("PACKED-DECIMAL")) {
            us = Usage.COMP3;
        } else if (u.equals("COMP-5")) {
            us = Usage.COMP5;
        } else {
            throw new IllegalArgumentException("unsupported USAGE " + usage);
        }
        String sc = sign == null ? "" : sign.toUpperCase();
        return new Pic(d, s, sg, us, sc.contains("LEADING"), sc.contains("SEPARATE"));
    }

    public static Pic parse(String picture, String usage) {
        return parse(picture, usage, "");
    }

    public static Pic parse(String picture) {
        return parse(picture, "", "");
    }

    @Override
    public boolean equals(Object o) {
        if (!(o instanceof Pic)) {
            return false;
        }
        Pic p = (Pic) o;
        return p.digits == digits && p.scale == scale && p.signed == signed && p.usage == usage
                && p.signLeading == signLeading && p.signSeparate == signSeparate;
    }

    @Override
    public int hashCode() {
        return ((digits * 31 + scale) * 31 + usage) * 8 + (signed ? 4 : 0) + (signLeading ? 2 : 0)
                + (signSeparate ? 1 : 0);
    }

    @Override
    public String toString() {
        StringBuilder b = new StringBuilder();
        if (signed) {
            b.append('S');
        }
        if (scale <= 0) {
            b.append("9(").append(digits).append(')');
            for (int i = 0; i < -scale; i++) {
                b.append('P');
            }
        } else if (scale >= digits) {
            b.append('V');
            for (int i = 0; i < scale - digits; i++) {
                b.append('P');
            }
            b.append("9(").append(digits).append(')');
        } else {
            b.append("9(").append(digits - scale).append(")V9(").append(scale).append(')');
        }
        String[] names = {"", " COMP", " COMP-3", " COMP-5"};
        b.append(names[usage]);
        if (signLeading || signSeparate) {
            b.append(signLeading ? " SIGN LEADING" : " SIGN TRAILING").append(signSeparate ? " SEPARATE" : "");
        }
        return b.toString();
    }
}
