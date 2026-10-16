"""Configuration. Weights live here, not in code paths, because the config
version is hashed into the attestation root: change a weight, change the root.
"""
from dataclasses import dataclass, field

# The only RPC we read. Finalised blocks only.
CHAIN_URL = "wss://mainnet.portaldot.io"

# Portaldot's own documentation names a preset that does not exist.
# This is the one that decodes the runtime.
TYPE_PRESET = "legacy"
SS58_FORMAT = 42

# An account whose public key is all zeros is credited with block production
# on this chain. It is not a validator and never enters the data.
ZERO_ACCOUNT = "5C4hrfjw9DjXZTzV3MwzrrAr9P1MJhSrvWGWqi1eSuyUpnhM"

# A single era cannot plausibly change total stake by this factor. If it does,
# we are reading something wrong and must stop rather than record nonsense.
# Era 3873 is the real precedent: the largest validator left the set for one
# era and total stake fell 7.9x. That is why the bound is generous and why
# crossing it halts instead of warning.
SANITY_STAKE_RATIO = 20.0


@dataclass(frozen=True)
class Weights:
    """Scoring weights in basis points. Must sum to 10 000 across active
    factors; inactive factors are renormalised at scoring time."""
    commission: int = 3500
    self_stake: int = 2000
    offences: int = 2000
    identity: int = 500
    # Added 16 October. Marked "does not separate" when the archive was
    # young; at 113 eras it separates clearly — one validator has been out
    # of the set for 15 of them, earning its delegators nothing, and no
    # other factor sees that.
    consistency: int = 2000

    def as_dict(self) -> dict[str, int]:
        return {"commission": self.commission, "self_stake": self.self_stake,
                "offences": self.offences, "identity": self.identity,
                "consistency": self.consistency}

    def by_factor_id(self) -> dict[str, int]:
        """Weights keyed by permanent factor id, which is what gets hashed.
        Names are presentation and may be renamed; ids never are."""
        return {"1": self.commission, "2": self.self_stake,
                "3": self.offences, "4": self.identity,
                "6": self.consistency}


@dataclass(frozen=True)
class Config:
    weights: Weights = field(default_factory=Weights)
    version: int = 2
    # A validator taking this much commission returns nothing to a nominator.
    gate_commission_bp: int = 10_000
    # No single validator receives more than this share of an allocation.
    max_share_bp: int = 2500
    # Chain limit on how many targets one nominator may submit.
    max_nominations: int = 16


    def canonical(self) -> dict:
        """Exactly what goes into the config leaf of the attestation tree.
        Key names and shape are part of the format: changing them changes
        every root ever produced."""
        return {
            "engine_version": self.version,
            "gate_commission_bp": self.gate_commission_bp,
            "cap_bp": self.max_share_bp,
            "max_targets": self.max_nominations,
            "weights": self.weights.by_factor_id(),
        }


DEFAULT = Config()
