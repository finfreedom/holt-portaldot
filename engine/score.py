"""S2 — rank validators on what can be measured.

Pure functions over the database. No network, no clock, no randomness: the
same era and the same config produce the same bytes, which is what makes the
attestation root in S4 worth anything.

Nine factors were designed. On this network four separate validators and the
rest return the same answer for everyone. A factor with no spread contributes
**zero**, not "the same to everyone" — it switches itself off and the
remaining weights are renormalised. Saying "does not separate" is more honest
than performing analysis where there is none.
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field

from .config import Config, DEFAULT
from .fixed import log2_fp, ratio_bp

# Factor ids are permanent and never reused: they are hashed into the root.
FACTOR_IDS = {
    "commission": 1,
    "self_stake": 2,
    "offences": 3,
    "identity": 4,
    "liveness": 5,
    "consistency": 6,
    "oversubscription": 7,
}


@dataclass
class FactorValue:
    name: str
    factor_id: int
    raw: int
    value_bp: int          # 0..10000 after normalisation, 0 when inactive
    weight_bp: int         # applied weight, 0 when inactive
    active: bool


@dataclass
class Score:
    address: str
    score_bp: int          # 0..10000, or 0 when gated
    gated: bool
    gate_reason: str | None
    factors: list[FactorValue] = field(default_factory=list)


def _raw_values(db: sqlite3.Connection, era: int) -> dict[str, dict[str, int]]:
    """Collect every factor's raw input for every validator in the era.

    `offences` is counted over all history, not just this era: a validator's
    record of unresponsiveness does not reset when an era turns.
    """
    rows = db.execute(
        "select address, own, total, commission_bp, reward_points, nominator_count"
        " from era_validators where era = ?", (era,)).fetchall()
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        own, total = int(r["own"]), int(r["total"])
        offences = db.execute(
            "select count(*) from offences where address = ?", (r["address"],)
        ).fetchone()[0]
        identity = db.execute(
            "select identity_json is not null from validators where address = ?",
            (r["address"],)).fetchone()
        out[r["address"]] = {
            # lower is better
            "commission": r["commission_bp"],
            # higher is better; log scale because the range spans 0.1%..100%
            "self_stake": log2_fp(1 + ratio_bp(own, total)),
            # lower is better; log scale because one validator has 93 and
            # most have single digits
            "offences": log2_fp(1 + offences),
            # higher is better, binary
            "identity": 1 if (identity and identity[0]) else 0,
        }
    return out


# True where a larger raw value means a better validator.
HIGHER_IS_BETTER = {
    "commission": False,
    "self_stake": True,
    "offences": False,
    "identity": True,
}


def normalise(raws: dict[str, int], higher_is_better: bool) -> dict[str, int] | None:
    """Map raw values onto 0..10000 against the observed range.

    Returns None when the range is empty — every validator answered the same,
    so the factor separates nothing and must be switched off rather than
    handed out uniformly.
    """
    values = list(raws.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return None
    span = hi - lo
    out = {}
    for addr, v in raws.items():
        bp = ((v - lo) * 10_000) // span
        out[addr] = bp if higher_is_better else 10_000 - bp
    return out


def score_era(db: sqlite3.Connection, era: int, cfg: Config = DEFAULT) -> list[Score]:
    """Score every validator in an era. Ordered by raw public key ascending —
    the canonical order, because the merkle tree depends on it."""
    raws = _raw_values(db, era)
    if not raws:
        return []

    weights = cfg.weights.as_dict()
    per_factor: dict[str, dict[str, int] | None] = {}
    for name in weights:
        per_factor[name] = normalise(
            {a: raws[a][name] for a in raws}, HIGHER_IS_BETTER[name])

    active_total = sum(w for n, w in weights.items() if per_factor[n] is not None)

    scores: list[Score] = []
    for address in sorted(raws):
        commission = raws[address]["commission"]
        gated = commission >= cfg.gate_commission_bp
        factors: list[FactorValue] = []
        acc = 0
        for name, weight in weights.items():
            norm = per_factor[name]
            is_active = norm is not None
            value_bp = norm[address] if is_active else 0
            factors.append(FactorValue(
                name=name, factor_id=FACTOR_IDS[name], raw=raws[address][name],
                value_bp=value_bp, weight_bp=weight if is_active else 0,
                active=is_active))
            if is_active:
                acc += weight * value_bp

        score_bp = 0 if (gated or active_total == 0) else acc // active_total
        scores.append(Score(
            address=address,
            score_bp=score_bp,
            gated=gated,
            # The gate suppresses the displayed score as well, not only
            # participation: otherwise a 100%-commission validator scores well
            # on self-stake and sorts above the largest one, which a reader
            # takes as a recommendation.
            gate_reason="commission 100%" if gated else None,
            factors=sorted(factors, key=lambda f: f.factor_id),
        ))
    return scores


def summary(scores: list[Score]) -> dict:
    """What the interface needs to say about a scoring run."""
    passing = [s for s in scores if not s.gated]
    inactive = sorted({f.name for s in scores for f in s.factors if not f.active})
    return {
        "validators": len(scores),
        "gated": len(scores) - len(passing),
        "inactive_factors": inactive,
        "best": max(passing, key=lambda s: s.score_bp).address if passing else None,
    }
