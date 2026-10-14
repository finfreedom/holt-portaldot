import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from engine.fixed import FRAC_BITS, log2_fp, ratio_bp   # noqa: E402


def test_log2_exact_powers():
    one = 1 << FRAC_BITS
    assert log2_fp(1) == 0
    assert log2_fp(2) == one
    assert log2_fp(4) == 2 * one
    assert log2_fp(1024) == 10 * one


def test_log2_matches_float_closely_but_uses_no_float():
    """Within half a unit in the last place of the fixed-point grid. The
    point is not that it equals math.log2 — it is that it never varies."""
    for x in (3, 5, 7, 93, 1000, 123_456, 4_194_640_029_197_252_300_000):
        got = log2_fp(x) / (1 << FRAC_BITS)
        assert abs(got - math.log2(x)) < 1e-4, x


def test_log2_is_monotonic():
    prev = -1
    for x in range(1, 5000):
        v = log2_fp(x)
        assert v >= prev
        prev = v


def test_log2_zero_and_negative_are_zero():
    assert log2_fp(0) == 0
    assert log2_fp(-5) == 0


def test_ratio_truncates_and_survives_u128():
    assert ratio_bp(1, 3) == 3333
    assert ratio_bp(0, 10) == 0
    assert ratio_bp(5, 0) == 0
    big = 4_194_640_029_197_252_300_000
    assert ratio_bp(big // 2, big) == 5000
