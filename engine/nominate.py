"""S5 (mainnet branch) — build a nomination plan without signing anything.

This is the product's actual output. Scoring answers "is this validator
sound?"; the plan answers the question a nominator actually has, which is
"where do I put my stake?"

Two things this module refuses to do, both deliberate:

**It does not promise proportions.** In NPoS a nominator submits a *set* of
targets and the election solver spreads their stake across that set. Nobody
hands the chain a percentage. A planner that reported "32% here, 18% there"
would be describing a chain that does not exist, so the plan reports the set
and what the set implies, and says the split is the election's to make.

**It does not sign.** The result is an unsigned call, printed. Holt holds no
authority over anyone's stake anywhere — no proxy, no pool role, no agent.
The nominator submits it themselves, or does not.

The plan is deterministic: same era, same config, same set. Anyone holding
the attestation root for that era can recompute it and get the same answer,
which is the point of publishing the root at all.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .config import DEFAULT, Config
from .score import score_era


@dataclass(frozen=True)
class Target:
    address: str
    score_bp: int
    stake_share_bp: int       # the validator's share of network stake
    reason: str


@dataclass(frozen=True)
class Plan:
    era: int
    targets: list[Target]
    excluded_gated: list[str]
    excluded_oversized: list[str]
    neff_portfolio: float     # if the election spreads evenly over the set
    neff_network: float       # the network as it stands
    max_targets: int
    threshold_bp: int         # the share above which allocation declines

    @property
    def call(self) -> dict:
        """The unsigned extrinsic. Printed, never submitted."""
        return {"call_module": "Staking", "call_function": "nominate",
                "call_args": {"targets": [t.address for t in self.targets]}}


def _neff(weights: list[float]) -> float:
    """Inverse Herfindahl. 1.0 means one holder; n means n equal holders."""
    total = sum(weights)
    if total <= 0:
        return 0.0
    return 1.0 / sum((w / total) ** 2 for w in weights)


def plan(db: sqlite3.Connection, era: int, cfg: Config = DEFAULT) -> Plan:
    """Target set for `era`: sound validators by descending score.

    Gated validators are excluded rather than ranked last. A validator taking
    100% commission is not a weak choice, it is not a choice — delegating to
    it returns exactly nothing — so it does not belong in an ordered list of
    options at all.
    """
    canon = cfg.canonical()
    max_targets = canon["max_targets"]

    scores = score_era(db, era, cfg)
    stake = {r[0]: int(r[1]) for r in db.execute(
        "select address, total from era_validators where era = ?", (era,))}
    network_total = sum(stake.values())

    def share_bp(addr: str) -> int:
        return (stake.get(addr, 0) * 10_000 // network_total
                if network_total else 0)

    gated = sorted(s.address for s in scores if s.gated)
    # The cap is where "scoring and allocation are separate" becomes a line
    # of code. An account holding most of the network scores fine on its own
    # conduct — it is not misbehaving — but sending more stake to it is the
    # exact thing this project exists to warn about, so allocation declines
    # where scoring does not.
    # The cap is an absolute 25%, but it is applied to a set whose size
    # varies, and a flat threshold misfires on a small one: three validators
    # holding a third each are not concentrated, they are three validators,
    # yet every one of them clears 25% and the plan comes back empty. So the
    # threshold is the cap OR an even share, whichever is larger — it bites
    # only where a validator holds more than its share of the room.
    n = max(1, len(scores))
    threshold = max(canon["cap_bp"], 10_000 // n)
    oversized = sorted(s.address for s in scores
                       if not s.gated and share_bp(s.address) > threshold)
    usable = sorted((s for s in scores
                     if not s.gated and share_bp(s.address) <= threshold),
                    key=lambda s: (-s.score_bp, s.address))[:max_targets]

    targets = []
    for s in usable:
        share = (stake.get(s.address, 0) * 10_000 // network_total
                 if network_total else 0)
        targets.append(Target(
            address=s.address,
            score_bp=s.score_bp,
            stake_share_bp=share,
            reason=_reason(s, usable),
        ))

    return Plan(
        era=era,
        targets=targets,
        excluded_gated=gated,
        excluded_oversized=oversized,
        # Equal weights: what the set implies if the election spreads across
        # it. Not a prediction of the solver's output, and labelled as such
        # wherever it is shown.
        neff_portfolio=round(_neff([1.0] * len(targets)), 2) if targets else 0.0,
        neff_network=round(_neff([float(v) for v in stake.values()]), 2),
        max_targets=max_targets,
        threshold_bp=threshold,
    )


def _reason(s, peers) -> str:
    """What sets this validator apart from the others on the list.

    The first version picked the largest weighted contribution and returned
    "lowest commission" for all six, because commission carries the heaviest
    weight and everyone scored near the top of it. A reason that every entry
    shares explains nothing. This picks the factor where the validator is
    furthest ABOVE its peers, which is the actual answer to "why is this one
    above that one?".
    """
    live = [f for f in s.factors if f.active]
    if not live:
        return "no factor separates on this era"

    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else 0

    peer_median = {}
    for f in live:
        peer_median[f.name] = median(
            [g.value_bp for p in peers for g in p.factors
             if g.name == f.name and g.active])
    lead = max(live, key=lambda f: f.value_bp - peer_median.get(f.name, 0))
    if lead.value_bp - peer_median.get(lead.name, 0) <= 0:
        return "no single factor puts it ahead; it is sound across all of them"
    best = lead
    words = {
        "commission": "lowest commission among sound validators",
        "self_stake": "high self-stake against total",
        "offences": "clean offence record",
        "identity": "on-chain identity set",
        "consistency": "present in the set every era we have",
    }
    return words.get(best.name, best.name)
