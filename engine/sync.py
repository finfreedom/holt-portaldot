"""S1 — pull finalised eras into the database.

Run it early and often. The staking pallet keeps 84 eras; everything older is
answered with zero. Depth of history is therefore bought with time, and the
only way to have a month of it at submission is to have started a month ago.

    python -m engine.sync                 # catch up to the current era
    python -m engine.sync --from 3800     # and no further back than this
    python -m engine.sync --dry-run       # read and report, write nothing
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from datetime import datetime, timezone

from . import db as database
from .chain import Chain, EraSnapshot
from .config import SANITY_STAKE_RATIO, ZERO_ACCOUNT


class SanityError(RuntimeError):
    """Total stake moved further in one era than any real event explains.
    Halting is the point: recording nonsense quietly is worse than stopping."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_sanity(db: sqlite3.Connection, snap: EraSnapshot) -> None:
    """Compare against the nearest earlier era we already hold."""
    row = db.execute(
        "select era, total_stake from eras where era < ? order by era desc limit 1",
        (snap.era,),
    ).fetchone()
    if not row:
        return
    before, now = int(row["total_stake"]), snap.total_stake
    if before == 0 or now == 0:
        return
    ratio = max(before, now) / min(before, now)
    if ratio > SANITY_STAKE_RATIO:
        raise SanityError(
            f"era {snap.era}: total stake moved {ratio:.1f}x against era "
            f"{row['era']} ({before} -> {now}). Refusing to write."
        )


def write_era(db: sqlite3.Connection, snap: EraSnapshot) -> None:
    """Idempotent on (era, address) and (era, nominator, validator):
    a re-run repairs rows rather than duplicating them."""
    real = [v for v in snap.validators if v["address"] != ZERO_ACCOUNT]
    db.execute(
        "insert or replace into eras(era, total_stake, validator_reward,"
        " total_points, validator_count, collected_at) values (?,?,?,?,?,?)",
        (snap.era, str(snap.total_stake),
         None if snap.validator_reward is None else str(snap.validator_reward),
         snap.total_points, len(real), _now()),
    )
    for v in snap.validators:
        if v["address"] == ZERO_ACCOUNT:
            continue
        db.execute(
            "insert into validators(address, pubkey, first_seen_era,"
            " last_seen_era, identity_json) values (?,?,?,?,?)"
            " on conflict(address) do update set"
            "   first_seen_era = min(first_seen_era, excluded.first_seen_era),"
            "   last_seen_era  = max(last_seen_era,  excluded.last_seen_era),"
            "   identity_json  = excluded.identity_json",
            (v["address"], b"", snap.era, snap.era, v.get("identity_json")),
        )
        db.execute(
            "insert or replace into era_validators"
            "(era, address, own, total, nominator_count, commission_bp,"
            " reward_points, is_active) values (?,?,?,?,?,?,?,?)",
            (snap.era, v["address"], str(v["own"]), str(v["total"]),
             v["nominator_count"], v["commission_bp"], v["reward_points"],
             v["is_active"]),
        )
    for n in snap.nominations:
        if n["nominator"] == ZERO_ACCOUNT:
            continue
        db.execute(
            "insert or replace into era_nominations(era, nominator, validator, amount)"
            " values (?,?,?,?)",
            (snap.era, n["nominator"], n["validator"], str(n["amount"])),
        )


def refresh_identities(db: sqlite3.Connection, chain: Chain, dry_run: bool = False) -> int:
    """Re-read on-chain identity for every validator we know.

    Identity belongs to the account, not to an era, and can be set or cleared
    at any time — so it is refreshed on every run, not only when a new era is
    fetched. It also matters that we look: the scoring factor reports "does
    not separate", and that claim must rest on our own data rather than on
    someone having checked by hand once.
    """
    rows = db.execute("select address from validators").fetchall()
    changed = 0
    for r in rows:
        ident = chain.identity(r["address"])
        if dry_run:
            continue
        cur = db.execute("select identity_json from validators where address = ?",
                         (r["address"],)).fetchone()["identity_json"]
        if cur != ident:
            db.execute("update validators set identity_json = ? where address = ?",
                       (ident, r["address"]))
            changed += 1
    return changed


def sync(db_path=None, oldest: int | None = None, dry_run: bool = False) -> dict:
    db = database.connect(db_path or database.DEFAULT_DB)
    chain = Chain()
    try:
        head = chain.finalised_number()
        current = chain.active_era()
        depth = chain.history_depth()
        floor = max(oldest or 0, current - depth)

        have = database.eras_present(db)
        todo = [e for e in range(floor, current + 1) if e not in have]

        print(f"finalised block {head}, active era {current}, "
              f"pallet answers from era {current - depth}")
        print(f"held {len(have)} eras, fetching {len(todo)}"
              + (" (dry run)" if dry_run else ""))

        written = 0
        for era in todo:
            snap = chain.era_snapshot(era)
            if snap is None:
                print(f"  era {era}: no data, skipped")
                continue
            check_sanity(db, snap)
            if dry_run:
                print(f"  era {era}: {len(snap.validators)} validators, "
                      f"{len(snap.nominations)} nominations (not written)")
                continue
            write_era(db, snap)
            db.commit()
            written += 1
            print(f"  era {era}: {len(snap.validators)} validators, "
                  f"{len(snap.nominations)} nominations")

        changed = refresh_identities(db, chain, dry_run)
        known = db.execute("select count(*) from validators").fetchone()[0]
        with_identity = db.execute(
            "select count(*) from validators where identity_json is not null"
        ).fetchone()[0]
        print(f"identity: {with_identity} of {known} validators have one"
              f"{'' if dry_run else f', {changed} updated'}")

        if not dry_run:
            database.meta_set(db, "last_sync", _now())
            database.meta_set(db, "last_finalised_block", head)
            db.commit()

        total = len(database.eras_present(db))
        print(f"done. {total} eras in the database, {written} written this run")
        return {"head": head, "era": current, "written": written, "total": total}
    finally:
        chain.close()
        db.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pull finalised eras into the database.")
    ap.add_argument("--db", default=None, help="path to the SQLite file")
    ap.add_argument("--from", dest="oldest", type=int, default=None,
                    help="do not fetch eras older than this")
    ap.add_argument("--dry-run", action="store_true",
                    help="read and report, write nothing")
    a = ap.parse_args(argv)
    try:
        sync(a.db, a.oldest, a.dry_run)
    except SanityError as e:
        print(f"HALTED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
