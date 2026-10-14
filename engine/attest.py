"""S4 — fix an era's scores on chain.

Computes the merkle root over the era's scores by the format in
docs/methodology.md, records it locally, and — when a target chain is
available — commits it with a single owner-only call:

    commit(era: u32, root: [u8;32], engine_version: u32)

Committing is not the hard part. The hard part is that the root must be
reproducible by someone who has only the chain and the written format, which
is why `verify/root.mjs` exists and is written from the document rather than
ported from this file.

    python -m engine.attest --era 3890            compute and record
    python -m engine.attest --era 3890 --show     print the leaves too
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
import sys

from . import db as database
from .config import Config, DEFAULT
from .merkle import canonical_config_bytes, era_root, validator_leaf
from .score import Score, score_era


def config_hash(cfg: Config) -> str:
    return hashlib.blake2b(canonical_config_bytes(cfg.canonical()),
                           digest_size=32).hexdigest()


def pubkeys(db: sqlite3.Connection) -> dict[str, bytes]:
    return {r["address"]: bytes(r["pubkey"])
            for r in db.execute("select address, pubkey from validators")}


def attest(db: sqlite3.Connection, era: int, cfg: Config = DEFAULT) -> dict:
    """Compute the root for an era and record it. Idempotent: the same era,
    engine version and config always produce the same row."""
    scores = score_era(db, era, cfg)
    if not scores:
        raise ValueError(f"no scores for era {era}")
    keys = pubkeys(db)
    missing = [s.address for s in scores if s.address not in keys]
    if missing:
        raise ValueError(f"no public key for {missing[0]} — cannot order leaves")

    root = era_root(scores, keys, cfg.canonical()).hex()
    chash = config_hash(cfg)

    for s in scores:
        db.execute(
            "insert or replace into scores(era, address, score_bp, gated,"
            " gate_reason, factors_json, engine_version, config_hash)"
            " values (?,?,?,?,?,?,?,?)",
            (era, s.address, s.score_bp, 1 if s.gated else 0, s.gate_reason,
             json.dumps([[f.factor_id, f.value_bp, f.weight_bp, int(f.active)]
                         for f in s.factors], separators=(",", ":")),
             cfg.version, chash))
    db.execute(
        "insert or replace into attestations(era, root, engine_version, config_hash)"
        " values (?,?,?,?)", (era, root, cfg.version, chash))
    db.commit()
    return {"era": era, "root": root, "config_hash": chash,
            "validators": len(scores),
            "gated": sum(1 for s in scores if s.gated)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compute and record an attestation root.")
    ap.add_argument("--db", default=None)
    ap.add_argument("--era", type=int, required=True)
    ap.add_argument("--show", action="store_true", help="print every leaf")
    a = ap.parse_args(argv)

    db = database.connect(a.db or database.DEFAULT_DB)
    try:
        out = attest(db, a.era)
        if a.show:
            keys = pubkeys(db)
            for s in sorted(score_era(db, a.era), key=lambda s: keys[s.address]):
                print(f"  {validator_leaf(keys[s.address], s).hex()}  "
                      f"{s.address[:14]}…  {'gated' if s.gated else s.score_bp}")
        print(f"era {out['era']}: {out['validators']} validators, "
              f"{out['gated']} gated")
        print(f"config  {out['config_hash']}")
        print(f"root    {out['root']}")
        print("\nverify independently:")
        print(f"  node verify/root.mjs <holt.db> {out['era']}")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
