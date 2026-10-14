"""The attestation format, byte for byte.

Specified in docs/methodology.md. The point of writing it down separately from
the code is that a second implementation can be built from the document alone;
one implementation proves only that the code agrees with itself.

blake2-256 everywhere, big-endian numbers, every hash domain-separated so a
leaf can never be passed off as an internal node.
"""
from __future__ import annotations
import hashlib
import json

from .score import Score

DOMAIN_VALIDATOR = b"holt.v1.validator"
DOMAIN_FACTORS = b"holt.v1.factors"
DOMAIN_CONFIG = b"holt.v1.config"
DOMAIN_NODE = b"holt.v1.node"


def h(*parts: bytes) -> bytes:
    d = hashlib.blake2b(digest_size=32)
    for p in parts:
        d.update(p)
    return d.digest()


def u8(n: int) -> bytes:
    return int(n).to_bytes(1, "big")


def u16(n: int) -> bytes:
    return int(n).to_bytes(2, "big")


def factors_hash(score: Score) -> bytes:
    """Factors in ascending factor_id. An inactive factor is included with
    weight zero rather than omitted: dropping it would make two different
    configurations hash alike."""
    body = b"".join(
        u8(f.factor_id) + u16(f.value_bp) + u16(f.weight_bp) + u8(1 if f.active else 0)
        for f in sorted(score.factors, key=lambda f: f.factor_id)
    )
    return h(DOMAIN_FACTORS, body)


def validator_leaf(pubkey: bytes, score: Score) -> bytes:
    if len(pubkey) != 32:
        raise ValueError(f"public key must be 32 bytes, got {len(pubkey)}")
    return h(DOMAIN_VALIDATOR, pubkey, u16(score.score_bp),
             u8(1 if score.gated else 0), factors_hash(score))


def canonical_config_bytes(cfg_dict: dict) -> bytes:
    """Sorted keys, no whitespace. The config version is part of the root:
    change a weight and the root changes with it."""
    return json.dumps(cfg_dict, sort_keys=True, separators=(",", ":")).encode()


def config_leaf(cfg_dict: dict) -> bytes:
    return h(DOMAIN_CONFIG, canonical_config_bytes(cfg_dict))


def build_root(leaves: list[bytes]) -> bytes:
    """Binary tree. An odd level duplicates its last node."""
    if not leaves:
        raise ValueError("no leaves")
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [h(DOMAIN_NODE, level[i], level[i + 1])
                 for i in range(0, len(level), 2)]
    return level[0]


def era_root(scores: list[Score], pubkeys: dict[str, bytes], cfg_dict: dict) -> bytes:
    """Leaves in canonical order: the config leaf first, then validators by
    ascending raw public key."""
    ordered = sorted(scores, key=lambda s: pubkeys[s.address])
    leaves = [config_leaf(cfg_dict)]
    leaves += [validator_leaf(pubkeys[s.address], s) for s in ordered]
    return build_root(leaves)
