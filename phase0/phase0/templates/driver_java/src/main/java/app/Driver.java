package app;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.UnaryOperator;

/**
 * Execution interface (agreement 4.2). Reads one request from stdin,
 * {"unit_id": "CALC-FEE", "state": {"WS-AMOUNT": "123.45"}}, runs the unit, and writes
 * {"unit_id": ..., "status": "ok"|"error", "message": ..., "state": {...}} to stdout.
 *
 * Phase 1 fills {@link #UNITS}: one entry per translated unit, mapping the input state (field_id to
 * canonical value, see {@link Canon}) to the output state. A unit signals a COBOL runtime failure
 * by throwing {@link Canon.UnitError}; any other exception is a bug and ends the driver.
 */
public final class Driver {
    private Driver() {}

    static final Map<String, UnaryOperator<Map<String, String>>> UNITS = new LinkedHashMap<>();

    static {
        // UNITS.put("CALC-FEE", state -> { Prog p = Prog.fromState(state); p.calcFee(); return p.toState(); });
    }

    public static void main(String[] args) throws IOException {
        String text = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        Map<String, Object> request = Json.parseObject(text);
        String unitId = Json.string(request.get("unit_id"));
        Map<String, String> state = Json.stringMap(request.get("state"));
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("unit_id", unitId);
        UnaryOperator<Map<String, String>> unit = UNITS.get(unitId);
        if (unit == null) {
            response.put("status", "error");
            response.put("message", "unknown unit_id " + unitId + "; known: " + UNITS.keySet());
            response.put("state", state);
        } else {
            try {
                Map<String, String> out = unit.apply(new LinkedHashMap<>(state));
                response.put("status", "ok");
                response.put("message", null);
                response.put("state", out);
            } catch (Canon.UnitError e) {
                response.put("status", "error");
                response.put("message", e.getMessage());
                response.put("state", state);
            }
        }
        System.out.write((Json.write(response) + "\n").getBytes(StandardCharsets.UTF_8));
        System.out.flush();
    }
}
