"""Integer-only arithmetic helpers.

Scores are hashed into an attestation root, so two runs must produce identical
bytes on any machine. Floating point is excluded entirely: `math.log` may
differ in the last place between libm implementations, and a one-bit
difference changes the root.
"""
from __future__ import annotations

FRAC_BITS = 16


def log2_fp(x: int, frac_bits: int = FRAC_BITS) -> int:
    """floor(log2(x) * 2**frac_bits) using integer arithmetic only.

    Standard shift-and-square algorithm: the integer part comes from the bit
    length, then each fractional bit is decided by squaring the normalised
    mantissa and testing whether it crossed 2.

    log2_fp(1) == 0; log2_fp(2) == 2**frac_bits; log2_fp(0) == 0 by convention.
    """
    if x <= 0:
        return 0
    n = x.bit_length() - 1
    result = n << frac_bits
    # y = x / 2**n in [1, 2), held as fixed point
    y = (x << frac_bits) >> n
    one = 1 << frac_bits
    two = one << 1
    for i in range(frac_bits):
        y = (y * y) >> frac_bits
        if y >= two:
            y >>= 1
            result += 1 << (frac_bits - 1 - i)
    return result


def ratio_bp(numerator: int, denominator: int) -> int:
    """numerator/denominator in basis points, truncating. 0 if denominator is 0."""
    if denominator == 0:
        return 0
    return (numerator * 10_000) // denominator
