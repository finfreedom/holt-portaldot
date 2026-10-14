"""Block authors — who actually produced each block of an era.

Separate from sync because it is slow: roughly 1.8 s per block over a remote
RPC, so one era of 720 blocks takes about twenty minutes. Running it inside
the ordinary sync would make a two-second job into a twenty-minute one.

It is worth the time because it answers a question stake alone cannot: the
network hands out block opportunities without regard to stake, so comparing
who works against who holds is the whole argument.

`Authorship.Author` does not resolve on this runtime. The author is in the
header's BABE pre-runtime digest, as an index into the session's validator
set — which changes per session, so the set is cached per session, not once.

    python -m engine.authors --era 3890
    python -m engine.authors --blocks 720        the last N finalised blocks
"""
from __future__ import annotations
import argparse
import sqlite3
import time

from . import db as database
from .chain import Chain
from .config import ZERO_ACCOUNT

SESSION_BLOCKS = 120


def ensure_table(db: sqlite3.Connection) -> None:
    db.execute("""create table if not exists block_authors (
        number    INTEGER PRIMARY KEY,
        author    TEXT NOT NULL,
        slot_idx  INTEGER NOT NULL,
        ts_ms     INTEGER,
        seen_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    db.commit()


def author_of(chain: Chain, number: int, cache: dict[int, list[str]]) -> tuple[str, int] | None:
    """Returns (address, authority_index), or None when the digest has no
    pre-runtime entry we can read."""
    bh = chain.rpc.get_block_hash(number)
    hdr = chain.rpc.get_block_header(block_hash=bh)
    idx = None
    for log in hdr["header"]["digest"]["logs"]:
        d = log.value if hasattr(log, "value") else log
        pre = (d or {}).get("PreRuntime")
        if pre and isinstance(pre.get("data"), dict):
            idx = pre["data"].get("authority_index")
    if idx is None:
        return None
    session = number // SESSION_BLOCKS
    if session not in cache:
        cache[session] = list(
            chain.rpc.query("Session", "Validators", block_hash=bh).value)
    vals = cache[session]
    if idx >= len(vals):
        return None
    return vals[idx], idx


def collect(db_path=None, era: int | None = None, blocks: int = 720) -> dict:
    db = database.connect(db_path or database.DEFAULT_DB)
    ensure_table(db)
    chain = Chain()
    try:
        head = chain.finalised_number()
        lo, hi = head - blocks + 1, head
        have = {n for (n,) in db.execute(
            "select number from block_authors where number between ? and ?", (lo, hi))}
        todo = [n for n in range(lo, hi + 1) if n not in have]
        print(f"finalised {head}; range {lo}..{hi}; held {len(have)}, fetching {len(todo)}")

        cache: dict[int, list[str]] = {}
        t0, done, fails = time.time(), 0, 0
        for i, n in enumerate(todo, 1):
            # A twenty-minute job over a public RPC will meet dropped
            # connections. Reconnecting and carrying on is the difference
            # between a job that finishes and one that needs watching.
            got = None
            for attempt in range(3):
                try:
                    got = author_of(chain, n, cache)
                    break
                except Exception as e:
                    fails += 1
                    print(f"  block {n}: {type(e).__name__} {str(e)[:50]}"
                          f" (attempt {attempt + 1})", flush=True)
                    db.commit()
                    time.sleep(2 * (attempt + 1))
                    try:
                        chain.close()
                    except Exception:
                        pass
                    chain = Chain()
                    cache.clear()
            if got is None:
                continue
            if not got or got[0] == ZERO_ACCOUNT:
                continue
            address, idx = got
            ts = chain.rpc.query("Timestamp", "Now",
                                 block_hash=chain.rpc.get_block_hash(n)).value
            db.execute("insert or replace into block_authors(number, author, slot_idx, ts_ms)"
                       " values (?,?,?,?)", (n, address, idx, ts))
            done += 1
            if i % 25 == 0:
                db.commit()
                rate = (time.time() - t0) / i
                print(f"  {i}/{len(todo)}  {rate:.2f}s/block  "
                      f"~{(len(todo) - i) * rate / 60:.1f} min left", flush=True)
        db.commit()

        rows = db.execute(
            "select author, count(*) c from block_authors where number between ? and ?"
            " group by author order by c desc", (lo, hi)).fetchall()
        total = sum(r["c"] for r in rows)
        print(f"\n{total} blocks, {len(rows)} authors"
              + (f", {fails} transient failures recovered" if fails else ""))
        for r in rows:
            print(f"   {r['author'][:14]}  {r['c']:4}  {r['c'] / total * 100:5.2f}%")
        return {"blocks": total, "authors": len(rows), "written": done}
    finally:
        chain.close()
        db.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collect block authors from BABE digests.")
    ap.add_argument("--db", default=None)
    ap.add_argument("--era", type=int, default=None, help="informational only")
    ap.add_argument("--blocks", type=int, default=720, help="how many finalised blocks")
    a = ap.parse_args(argv)
    collect(a.db, a.era, a.blocks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
