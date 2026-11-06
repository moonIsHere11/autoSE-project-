package cobolrt;

import java.io.IOException;
import java.io.InputStream;

/**
 * ACCEPT from standard input, as GnuCOBOL 3.2 reads it: one line per ACCEPT (bytes up to '\n',
 * no other translation), a last line without '\n' is read normally, and at end of input the item
 * is set to spaces/zero (not left unchanged). The parsing rules live in
 * {@link CobolDecimal#accept(byte[])} (DISPLAY items take the first byte-length characters,
 * COMP/COMP-3/COMP-5 the whole line, COMP-5 wraps) and {@link PicX#accept(byte[])}.
 */
public final class Accept {
    private final InputStream in;

    public Accept(InputStream in) {
        this.in = in;
    }

    /** Next line without its newline, or null at end of input. */
    public byte[] readLine() {
        try {
            java.io.ByteArrayOutputStream b = new java.io.ByteArrayOutputStream();
            int c = in.read();
            if (c < 0) {
                return null;
            }
            while (c >= 0 && c != '\n') {
                b.write(c);
                c = in.read();
            }
            return b.toByteArray();
        } catch (IOException e) {
            return null;
        }
    }

    public void into(CobolDecimal item) {
        item.accept(readLine());
    }

    public void into(PicX item) {
        item.accept(readLine());
    }
}
