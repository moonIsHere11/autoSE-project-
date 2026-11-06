"""Q6: T3-style contracts (icontract) and plain asserts.

Pre: inputs in PIC domain. Post: result in PIC domain AND equal to an exact formula
(the formula is the COBOL semantics written independently of the implementation).
"""
import icontract

P7 = 10**7


def _exact_add_trunc(a: int, b: int) -> int:
    # exact formula: sign(a+b) * (|a+b| mod 10^7)
    return (1 if a + b >= 0 else -1) * (abs(a + b) % P7)


def _exact_round2(v: int) -> int:
    # exact formula: sign(v) * floor((|v| + 50) / 100)
    return (1 if v >= 0 else -1) * ((abs(v) + 50) // 100)


# ---------------------------------------------------------------- PASS cases
@icontract.require(lambda a: -P7 < a < P7)
@icontract.require(lambda b: -P7 < b < P7)
@icontract.ensure(lambda result: -P7 < result < P7)
@icontract.ensure(lambda a, b, result: result == _exact_add_trunc(a, b))
def add_ok(a: int, b: int) -> int:
    s = a + b
    if s >= P7:
        s -= P7
    elif s <= -P7:
        s += P7
    return s


@icontract.require(lambda v: -10**9 < v < 10**9)
@icontract.ensure(lambda result: -10**7 < result < 10**7)
@icontract.ensure(lambda v, result: result == _exact_round2(v))
def round_ok(v: int) -> int:
    q, r = divmod(abs(v), 100)
    if r >= 50:
        q += 1
    return q if v >= 0 else -q


# ---------------------------------------------------------------- FAIL cases
@icontract.require(lambda a: -P7 < a < P7)
@icontract.require(lambda b: -P7 < b < P7)
@icontract.ensure(lambda result: -P7 < result < P7)
@icontract.ensure(lambda a, b, result: result == _exact_add_trunc(a, b))
def add_bug_notrunc(a: int, b: int) -> int:
    return a + b


@icontract.require(lambda v: -10**9 < v < 10**9)
@icontract.ensure(lambda result: -10**7 < result < 10**7)
@icontract.ensure(lambda v, result: result == _exact_round2(v))
def round_bug_banker(v: int) -> int:
    return round(v / 100)


@icontract.require(lambda v: -10**9 < v < 10**9)
@icontract.ensure(lambda v, result: result == _exact_round2(v))
def round_bug_raises(v: int) -> int:
    if v == 777:
        raise ValueError("boom")
    return _exact_round2(v)
