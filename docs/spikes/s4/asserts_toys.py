"""Q6b: --analysis_kind=asserts (leading asserts = preconditions; any later failing assert = counterexample)."""

P7 = 10**7


def add_ok(a: int, b: int) -> int:
    assert -P7 < a < P7
    assert -P7 < b < P7
    s = a + b
    r = (1 if s >= 0 else -1) * (abs(s) % P7)
    assert -P7 < r < P7
    return r


def add_bug(a: int, b: int) -> int:
    assert -P7 < a < P7
    assert -P7 < b < P7
    r = a + b
    assert -P7 < r < P7, "result out of PIC S9(7)"
    return r
