package app;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Minimal JSON reader/writer for the execution interface (objects, arrays, strings, null, literals). */
public final class Json {
    private Json() {}

    private final static class Reader {
        private final String s;
        private int i;

        Reader(String s) {
            this.s = s;
        }

        void ws() {
            while (i < s.length() && Character.isWhitespace(s.charAt(i))) {
                i++;
            }
        }

        char peek() {
            ws();
            if (i >= s.length()) {
                throw new IllegalArgumentException("unexpected end of JSON");
            }
            return s.charAt(i);
        }

        void expect(char c) {
            if (peek() != c) {
                throw new IllegalArgumentException("expected '" + c + "' at " + i);
            }
            i++;
        }

        Object value() {
            char c = peek();
            if (c == '{') {
                return object();
            }
            if (c == '[') {
                return array();
            }
            if (c == '"') {
                return string();
            }
            return literal();
        }

        Map<String, Object> object() {
            Map<String, Object> m = new LinkedHashMap<>();
            expect('{');
            if (peek() == '}') {
                i++;
                return m;
            }
            while (true) {
                String k = string();
                expect(':');
                m.put(k, value());
                if (peek() == ',') {
                    i++;
                    continue;
                }
                expect('}');
                return m;
            }
        }

        List<Object> array() {
            List<Object> a = new ArrayList<>();
            expect('[');
            if (peek() == ']') {
                i++;
                return a;
            }
            while (true) {
                a.add(value());
                if (peek() == ',') {
                    i++;
                    continue;
                }
                expect(']');
                return a;
            }
        }

        String string() {
            expect('"');
            StringBuilder b = new StringBuilder();
            while (true) {
                char c = s.charAt(i++);
                if (c == '"') {
                    return b.toString();
                }
                if (c != '\\') {
                    b.append(c);
                    continue;
                }
                char e = s.charAt(i++);
                switch (e) {
                    case 'n': b.append('\n'); break;
                    case 't': b.append('\t'); break;
                    case 'r': b.append('\r'); break;
                    case 'b': b.append('\b'); break;
                    case 'f': b.append('\f'); break;
                    case 'u': b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                    default: b.append(e);
                }
            }
        }

        Object literal() {
            int start = i;
            while (i < s.length() && ",}] \t\r\n".indexOf(s.charAt(i)) < 0) {
                i++;
            }
            String t = s.substring(start, i);
            if (t.equals("null")) {
                return null;
            }
            if (t.equals("true") || t.equals("false")) {
                return Boolean.valueOf(t);
            }
            return t;
        }
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> parseObject(String text) {
        Object v = new Reader(text).value();
        if (!(v instanceof Map)) {
            throw new IllegalArgumentException("request must be a JSON object");
        }
        return (Map<String, Object>) v;
    }

    public static String string(Object v) {
        if (!(v instanceof String)) {
            throw new IllegalArgumentException("expected a JSON string, got " + v);
        }
        return (String) v;
    }

    public static Map<String, String> stringMap(Object v) {
        Map<String, String> out = new LinkedHashMap<>();
        if (v == null) {
            return out;
        }
        if (!(v instanceof Map)) {
            throw new IllegalArgumentException("state must be a JSON object");
        }
        for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
            out.put((String) e.getKey(), string(e.getValue()));
        }
        return out;
    }

    public static String write(Object v) {
        StringBuilder b = new StringBuilder();
        write(b, v);
        return b.toString();
    }

    private static void write(StringBuilder b, Object v) {
        if (v == null) {
            b.append("null");
        } else if (v instanceof String) {
            quote(b, (String) v);
        } else if (v instanceof Map) {
            b.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                if (!first) {
                    b.append(", ");
                }
                first = false;
                quote(b, String.valueOf(e.getKey()));
                b.append(": ");
                write(b, e.getValue());
            }
            b.append('}');
        } else if (v instanceof List) {
            b.append('[');
            boolean first = true;
            for (Object x : (List<?>) v) {
                if (!first) {
                    b.append(", ");
                }
                first = false;
                write(b, x);
            }
            b.append(']');
        } else {
            b.append(v);
        }
    }

    private static void quote(StringBuilder b, String s) {
        b.append('"');
        for (int k = 0; k < s.length(); k++) {
            char c = s.charAt(k);
            if (c == '"' || c == '\\') {
                b.append('\\').append(c);
            } else if (c < 0x20 || c > 0x7E) {
                b.append(String.format("\\u%04x", (int) c));
            } else {
                b.append(c);
            }
        }
        b.append('"');
    }
}
