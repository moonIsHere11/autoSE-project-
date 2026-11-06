"""T3 verification copy: bodies of methods not under check are elided (OpenJML DEFERRED crash workaround)."""

from __future__ import annotations

from pathlib import Path

from verifier.tiers.t3_contracts import ELIDED_BODY, elide_bodies

SRC = """package corpus;
public class Demo {
    long wsA;
    String wsName = "    ";
    Demo() { wsA = 1; }
    void computeTax() { wsA = wsA + 1; }
    static long deedit(String s, int w) { return s.length(); }
    String fmt(String s, int w) {
        return String.valueOf(deedit(s.length() > w ? s.substring(0, w) : s, w));
    }
    Runnable r() { return new Runnable() { public void run() { } }; }
}
"""


def test_elides_everything_but_the_units(tmp_path: Path) -> None:
    p = tmp_path / "Demo.java"
    p.write_text(SRC, "utf-8")
    n = elide_bodies(p, {"computeTax"})
    out = p.read_text("utf-8")
    assert n == 3  # deedit, fmt, r (the anonymous run() goes with r's body)
    assert "void computeTax() { wsA = wsA + 1; }" in out  # unit body kept verbatim
    assert "Demo() { wsA = 1; }" in out  # constructor kept
    assert 'String wsName = "    ";' in out  # field initialiser kept
    assert "s.length() > w ?" not in out  # the construct that crashes OpenJML is gone
    assert out.count(ELIDED_BODY) == 3
