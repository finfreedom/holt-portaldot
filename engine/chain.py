"""The only module that talks to the chain.

Everything downstream works against the database and knows nothing about RPC,
which is what lets scoring be tested on fixtures without a node.

Two things on this runtime are not what the documentation says:
  * the type registry preset is `legacy`, not the one their docs name;
  * `Authorship.Author` does not resolve — the block author lives in the
    BABE pre-runtime digest as an index into the session's validator set.
"""
from __future__ import annotations
import json
from dataclasses import dataclass

from substrateinterface import SubstrateInterface

from .config import CHAIN_URL, SS58_FORMAT, TYPE_PRESET, ZERO_ACCOUNT


@dataclass
class EraSnapshot:
    """Everything one era contributes, read at a single finalised block."""
    era: int
    total_stake: int
    validator_reward: int | None
    total_points: int
    validators: list[dict]          # address, own, total, nominator_count, …
    nominations: list[dict]         # nominator, validator, amount
    active: set[str]                # addresses in session.validators


class Chain:
    def __init__(self, url: str = CHAIN_URL):
        self.url = url
        self.rpc = SubstrateInterface(
            url=url, ss58_format=SS58_FORMAT, type_registry_preset=TYPE_PRESET
        )

    # ── heads ────────────────────────────────────────────────────────────
    def finalised_number(self) -> int:
        """The latest finalised block. Nothing unfinalised is ever indexed:
        a reorg would otherwise write history that did not happen."""
        return self.rpc.get_block_number(self.rpc.get_chain_finalised_head())

    def finalised_hash(self) -> str:
        return self.rpc.get_chain_finalised_head()

    def is_finalised(self, number: int) -> bool:
        return number <= self.finalised_number()

    def active_era(self) -> int:
        return self.rpc.query("Staking", "ActiveEra").value["index"]

    def history_depth(self) -> int:
        """How many eras the staking pallet still answers for. Everything
        older is dropped from current state — which is why we keep our own."""
        try:
            return int(self.rpc.get_constant("Staking", "HistoryDepth").value)
        except Exception:
            return 84

    # ── era data ─────────────────────────────────────────────────────────
    def era_points(self, era: int) -> tuple[int, dict[str, int]]:
        """Reward points per validator. The zero account is dropped here, at
        the only door it can enter through.

        `individual` arrives as a list of pairs on this runtime, not the dict
        polkadot-js returns.
        """
        pts = self.rpc.query("Staking", "ErasRewardPoints", [era]).value
        raw = pts["individual"]
        pairs = raw.items() if hasattr(raw, "items") else raw
        individual = {addr: int(p) for addr, p in pairs if addr != ZERO_ACCOUNT}
        return int(pts["total"]), individual

    def era_exposure(self, era: int, address: str) -> dict:
        """One validator's exposure: own stake, total, and every nomination
        backing it."""
        exp = self.rpc.query("Staking", "ErasStakers", [era, address]).value
        others = exp.get("others") or []
        return {
            "own": int(exp["own"]),
            "total": int(exp["total"]),
            "others": [{"who": o["who"], "value": int(o["value"])} for o in others],
        }

    def era_commission_bp(self, era: int, address: str) -> int:
        prefs = self.rpc.query("Staking", "ErasValidatorPrefs", [era, address]).value
        # Perbill: parts per billion. Basis points are what we store.
        return int(prefs["commission"]) // 100_000

    def identity(self, address: str) -> str | None:
        """On-chain identity as canonical JSON, or None when unset.

        Collected even though no validator on this network has one: the
        scoring factor reports "does not separate", and that claim has to be
        backed by our own data rather than by someone having checked once.
        """
        try:
            raw = self.rpc.query("Identity", "IdentityOf", [address]).value
        except Exception:
            return None
        if not raw:
            return None
        return json.dumps(raw, sort_keys=True, separators=(",", ":"))

    def session_validators(self) -> list[str]:
        return list(self.rpc.query("Session", "Validators").value)

    def era_snapshot(self, era: int) -> EraSnapshot | None:
        """Everything about one era, or None if the chain no longer answers."""
        total_points, points = self.era_points(era)
        if not points:
            return None

        total_stake = int(self.rpc.query("Staking", "ErasTotalStake", [era]).value or 0)
        reward = self.rpc.query("Staking", "ErasValidatorReward", [era]).value
        active = set(self.session_validators())

        validators, nominations = [], []
        for address, pts in points.items():
            exp = self.era_exposure(era, address)
            validators.append({
                "address": address,
                "identity_json": self.identity(address),
                "own": exp["own"],
                "total": exp["total"],
                "nominator_count": len(exp["others"]),
                "commission_bp": self.era_commission_bp(era, address),
                "reward_points": pts,
                "is_active": 1 if address in active else 0,
            })
            for o in exp["others"]:
                nominations.append({
                    "nominator": o["who"], "validator": address, "amount": o["value"],
                })

        return EraSnapshot(
            era=era,
            total_stake=total_stake,
            validator_reward=int(reward) if reward is not None else None,
            total_points=total_points,
            validators=validators,
            nominations=nominations,
            active=active,
        )

    def close(self) -> None:
        try:
            self.rpc.close()
        except Exception:
            pass
