"""Alternative to diffbehavior: one generated function per unit, checked with
`crosshair check --analysis_kind=asserts`. Leading asserts = PIC-domain preconditions (handled
natively: violating inputs are discarded), last assert = behavioural equivalence of the
(return value, exception type, post-state) outcome."""
import cobol_ref as R
import llm_variants as L
import misc_toys as M


def _outcome(f, *args):
    try:
        return ("ok", f(*args))
    except Exception as e:  # CrossHair's internal control-flow exceptions are BaseException
        return ("exc", type(e).__name__)


def eq_round_decimal(v: int) -> None:
    assert -10**9 < v < 10**9
    assert _outcome(R.ref_round_drop2, v) == _outcome(L.round_ok_decimal, v)


def eq_round_banker(v: int) -> None:
    assert -10**9 < v < 10**9
    assert _outcome(R.ref_round_drop2, v) == _outcome(L.round_bug_banker, v)


def eq_round_floor(v: int) -> None:
    assert -10**9 < v < 10**9
    assert _outcome(R.ref_round_drop2, v) == _outcome(L.round_bug_floor, v)


def eq_div_msg(a: int, b: int) -> None:  # same type, different message -> equivalent here
    assert -10**7 < a < 10**7
    assert -10**7 < b < 10**7
    assert _outcome(M.ref_div, a, b) == _outcome(M.llm_div_msg, a, b)


def eq_div_type(a: int, b: int) -> None:  # different exception type -> counterexample
    assert -10**7 < a < 10**7
    assert -10**7 < b < 10**7
    assert _outcome(M.ref_div, a, b) == _outcome(M.llm_div_type, a, b)
