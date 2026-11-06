"""Q2: ways to restrict diffbehavior's inputs to a PIC domain.

A) guard_*  : identical generated guard in both wrappers, early-return a sentinel when out of domain.
B) ign_*    : identical guard raising crosshair.IgnoreAttempt (CrossHair's own "discard this input").
C) ann_*    : typing.Annotated metadata (expected to be ignored by CrossHair).
D) icr_*    : icontract.require on both wrappers (does diffbehavior honour preconditions?).
E) eq_*     : no diffbehavior at all: single function, preconditions + `ref == llm` as postcondition,
              checked with `crosshair check` (asserts / icontract kinds).
"""
from typing import Annotated

import icontract
from crosshair import IgnoreAttempt

import cobol_ref as R
import llm_variants as L

P7 = 10**7
_OUT = None  # sentinel; must be identical in ref and llm wrappers


def _in7(x: int) -> bool:
    return -P7 < x < P7


# ---------------------------------------------------------------- A) sentinel guard
def guard_ref_add(a: int, b: int) -> int | None:
    if not (_in7(a) and _in7(b)):
        return _OUT
    return R.ref_add_trunc(a, b)


def guard_llm_add_in_domain(a: int, b: int) -> int | None:
    if not (_in7(a) and _in7(b)):
        return _OUT
    return L.add_ok_in_domain(a, b)


def guard_llm_add_notrunc(a: int, b: int) -> int | None:
    if not (_in7(a) and _in7(b)):
        return _OUT
    return L.add_bug_notrunc(a, b)


def guard_ref_round(v: int) -> int | None:  # v: PIC S9(5)V9(4) -> |v| < 10**9
    if not -10**9 < v < 10**9:
        return _OUT
    return R.ref_round_drop2(v)


def guard_llm_round_decimal(v: int) -> int | None:
    if not -10**9 < v < 10**9:
        return _OUT
    return L.round_ok_decimal(v)


# ---------------------------------------------------------------- B) IgnoreAttempt guard
def ign_ref_add(a: int, b: int) -> int:
    if not (_in7(a) and _in7(b)):
        raise IgnoreAttempt
    return R.ref_add_trunc(a, b)


def ign_llm_add_in_domain(a: int, b: int) -> int:
    if not (_in7(a) and _in7(b)):
        raise IgnoreAttempt
    return L.add_ok_in_domain(a, b)


def ign_llm_add_notrunc(a: int, b: int) -> int:
    if not (_in7(a) and _in7(b)):
        raise IgnoreAttempt
    return L.add_bug_notrunc(a, b)


# ---------------------------------------------------------------- C) Annotated (metadata only)
Pic7 = Annotated[int, "PIC S9(7)", (-P7 + 1, P7 - 1)]


def ann_ref_add(a: Pic7, b: Pic7) -> int:
    return R.ref_add_trunc(a, b)


def ann_llm_add_in_domain(a: Pic7, b: Pic7) -> int:
    return L.add_ok_in_domain(a, b)


# ---------------------------------------------------------------- D) icontract.require on both
@icontract.require(lambda a, b: -P7 < a < P7 and -P7 < b < P7)
def icr_ref_add(a: int, b: int) -> int:
    return R.ref_add_trunc(a, b)


@icontract.require(lambda a, b: -P7 < a < P7 and -P7 < b < P7)
def icr_llm_add_in_domain(a: int, b: int) -> int:
    return L.add_ok_in_domain(a, b)


# ---------------------------------------------------------------- E) equivalence as a contract
def eq_asserts_add_in_domain(a: int, b: int) -> None:
    assert -P7 < a < P7  # leading asserts = preconditions in --analysis_kind=asserts
    assert -P7 < b < P7
    assert L.add_ok_in_domain(a, b) == R.ref_add_trunc(a, b)


def eq_asserts_add_notrunc(a: int, b: int) -> None:
    assert -P7 < a < P7
    assert -P7 < b < P7
    assert L.add_bug_notrunc(a, b) == R.ref_add_trunc(a, b)


@icontract.require(lambda a, b: -P7 < a < P7 and -P7 < b < P7)
@icontract.ensure(lambda a, b, result: result == R.ref_add_trunc(a, b))
def eq_icontract_add_in_domain(a: int, b: int) -> int:
    return L.add_ok_in_domain(a, b)


@icontract.require(lambda a, b: -P7 < a < P7 and -P7 < b < P7)
@icontract.ensure(lambda a, b, result: result == R.ref_add_trunc(a, b))
def eq_icontract_add_notrunc(a: int, b: int) -> int:
    return L.add_bug_notrunc(a, b)
