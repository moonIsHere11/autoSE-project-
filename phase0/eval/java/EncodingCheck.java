package app;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;

/** Checks app.Canon against kb/target/encoding_fixtures.json (path in args[0]); not shipped in the project, because the verifier lints every project file; exit 1 on the first mismatch. */
public final class EncodingCheck {
    private EncodingCheck() {}

    public static void main(String[] args) throws IOException {
        String text = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
        Map<String, Object> fx = Json.parseObject(text);
        int n = 0;
        for (Object o : (List<?>) fx.get("decimal")) {
            Map<?, ?> c = (Map<?, ?>) o;
            long u = Long.parseLong((String) c.get("unscaled"));
            int scale = Integer.parseInt((String) c.get("scale"));
            boolean nz = Boolean.TRUE.equals(c.get("negative_zero"));
            check(c, Canon.decimal(u, scale, nz));
            if (Canon.unscaled((String) c.get("canonical"), scale) != u) {
                fail(c, "unscaled round trip");
            }
            n++;
        }
        for (Object o : (List<?>) fx.get("alnum")) {
            Map<?, ?> c = (Map<?, ?>) o;
            check(c, Canon.alnum((String) c.get("value"), Integer.parseInt((String) c.get("length"))));
            n++;
        }
        for (Object o : (List<?>) fx.get("keys")) {
            Map<?, ?> c = (Map<?, ?>) o;
            List<?> subs = (List<?>) c.get("subscripts");
            int[] s = new int[subs.size()];
            for (int i = 0; i < s.length; i++) {
                s[i] = Integer.parseInt((String) subs.get(i));
            }
            check(c, Canon.key((String) c.get("field_id"), s));
            n++;
        }
        System.out.println("encoding fixtures ok: " + n);
    }

    private static void check(Map<?, ?> c, String got) {
        if (!got.equals(c.get("canonical"))) {
            fail(c, "got '" + got + "'");
        }
    }

    private static void fail(Map<?, ?> c, String why) {
        System.out.println("encoding fixture failed: " + c.get("case") + ": " + why);
        System.exit(1);
    }
}
