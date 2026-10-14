#!/usr/bin/env python3
"""S3 — render the site from the database.

Static output on purpose. The site is a report on measured state, not an
application: every figure belongs to a named era and does not move until the
next one closes. Static means no server, no database in production, and a
published page that can be archived and shown later exactly as it stood.

    python3 web/build.py            render into web/dist
    python3 web/build.py --serve    render and serve on :8000
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from engine import db as database          # noqa: E402
from engine.config import DEFAULT          # noqa: E402
from engine.score import score_era         # noqa: E402

TEMPLATES = pathlib.Path(__file__).parent / "templates"
DIST = pathlib.Path(__file__).parent / "dist"

BLOCK_SECONDS = 60
BLOCKS_PER_ERA = 720
HISTORY_DEPTH = 84

# The headline spells the count as a word: "Ten validators" reads as a
# sentence, "10 validators" reads as an instrument panel.
WORDS = {8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve",
         13: "Thirteen", 14: "Fourteen", 15: "Fifteen", 16: "Sixteen"}


def neff(values: list[int]) -> float:
    """Inverse Herfindahl index: how many equal holders the distribution
    behaves like."""
    total = sum(values)
    if not total:
        return 0.0
    return 1 / sum((v / total) ** 2 for v in values)


def ago(blocks: int) -> str:
    h = blocks * BLOCK_SECONDS / 3600
    if h < 1.5:
        return f"{round(h * 60)} min ago"
    if h < 48:
        return f"{round(h)} h ago"
    return f"{round(h / 24)} days ago"


def gather(db: sqlite3.Connection) -> dict:
    era_now = db.execute("select max(era) e from era_validators").fetchone()["e"]
    oldest = db.execute("select min(era) e from era_validators").fetchone()["e"]
    era_count = db.execute("select count(distinct era) c from era_validators").fetchone()["c"]

    rows = [dict(r) for r in db.execute(
        "select * from era_validators where era = ? order by cast(total as integer) desc",
        (era_now,))]
    stake = [int(r["total"]) for r in rows]
    total = sum(stake)

    # Authors are collected separately and may lag the latest era. Use the
    # most recent window we actually have, and say which it is.
    authors = db.execute(
        "select author, count(*) c from block_authors group by author order by c desc"
    ).fetchall()
    author_total = sum(r["c"] for r in authors)
    work = {r["author"]: r["c"] for r in authors}
    seq_order = [r["address"] for r in rows]
    idx = {a: i for i, a in enumerate(seq_order)}
    seq_rows = db.execute("select author from block_authors order by number").fetchall()
    seq = "".join(chr(97 + idx[r["author"]]) for r in seq_rows if r["author"] in idx)

    scores = {s.address: s for s in score_era(db, era_now, DEFAULT)}
    noms = {r["validator"]: r["c"] for r in db.execute(
        "select validator, count(*) c from era_nominations where era = ? group by validator",
        (era_now,))}
    offences = {r["address"]: r["c"] for r in db.execute(
        "select address, count(*) c from offences group by address")}

    V = []
    for r in rows:
        a = r["address"]
        # Short keys, matching what the page script reads:
        # a address, s stake share, w work share, b blocks, n delegators,
        # c commission, o offences, sc score (null when gated).
        V.append({
            "a": a[:12],
            "s": round(int(r["total"]) / total * 100, 2) if total else 0,
            "w": round(work.get(a, 0) / author_total * 100, 2) if author_total else 0,
            "b": work.get(a, 0),
            "n": noms.get(a, 0),
            "c": r["commission_bp"] / 100,
            "o": offences.get(a, 0),
            "sc": None if scores[a].gated else scores[a].score_bp,
        })

    # N_eff over every archived era, for the band shown on the page
    band = []
    for (e,) in db.execute("select distinct era from era_validators order by era"):
        xs = [int(x[0]) for x in db.execute(
            "select total from era_validators where era = ?", (e,))]
        if sum(xs):
            band.append(round(neff(xs), 4))

    win = db.execute("select min(number) lo, max(number) hi from block_authors").fetchone()
    head = int(database.meta_get(db, "last_finalised_block") or 0)
    counts = {
        "validator_rows": db.execute("select count(*) c from era_validators").fetchone()["c"],
        "nominations": db.execute("select count(*) c from era_nominations").fetchone()["c"],
        "offences": db.execute("select count(*) c from offences").fetchone()["c"],
        "authors": author_total,
    }

    return {
        "era_now": era_now, "oldest": oldest, "era_count": era_count,
        "block": head, "V": V, "seq": seq,
        "neff_stake": round(neff(stake), 2),
        "neff_work": round(neff(list(work.values())), 2) if work else 0,
        "top_stake": V[0]["s"] if V else 0,
        "top_work": V[0]["w"] if V else 0,
        "busiest": max((v["b"] for v in V), default=0),
        "quietest": min((v["b"] for v in V if v["b"]), default=0),
        "band_min": min(band) if band else 0, "band_max": max(band) if band else 0,
        "counts": counts,
        # Work and stake come from different samples: stake is an era
        # snapshot, work is a window of blocks collected separately and
        # slowly. The window is labelled on the page, because two samples
        # shown side by side otherwise read as one.
        "work_lo": win["lo"] or 0, "work_hi": win["hi"] or 0,
    }


def render(d: dict) -> str:
    tpl = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    boundary = d["era_now"] - HISTORY_DEPTH + 1
    repl = {
        "V": json.dumps(d["V"], separators=(",", ":")),
        "SEQ": d["seq"],
        "BLOCK": f"{d['block']:,}".replace(",", " "),
        "NEXT_IN": "60",
        "ERA_NOW": str(d["era_now"]),
        "ERA_NOW_AGO": "in progress",
        "ERA_CLOSED": str(d["era_now"] - 1),
        "ERA_CLOSED_AGO": ago(BLOCKS_PER_ERA),
        "BLOCKS_IN_ERA": str(BLOCKS_PER_ERA),
        "NEFF_STAKE": f"{d['neff_stake']:.2f}",
        "NEFF_WORK": f"{d['neff_work']:.2f}",
        "TOP_STAKE": f"{d['top_stake']:.2f}",
        "TOP_WORK": f"{d['top_work']:.2f}",
        "BUSIEST": str(d["busiest"]),
        "QUIETEST": str(d["quietest"]),
        "BOUNDARY_ERA": str(boundary),
        "HISTORY_DEPTH": str(HISTORY_DEPTH),
        "HISTORY_DAYS": str(HISTORY_DEPTH * BLOCKS_PER_ERA * BLOCK_SECONDS // 86400),
        "OLDEST_ERA": str(d["oldest"]),
        "ARCHIVE_AGO": ago((d["era_now"] - d["oldest"]) * BLOCKS_PER_ERA),
        "ERA_COUNT": str(d["era_count"]),
        "N_VALIDATORS_WORD": WORDS.get(len(d["V"]), str(len(d["V"]))),
        "NEFF_MIN": f"{d['band_min']:.4f}",
        "NEFF_MAX": f"{d['band_max']:.4f}",
        "N_VALIDATOR_ROWS": f"{d['counts']['validator_rows']:,}".replace(",", " "),
        "N_NOMINATIONS": f"{d['counts']['nominations']:,}".replace(",", " "),
        "N_OFFENCES": str(d["counts"]["offences"]),
        "N_AUTHORS": str(d["counts"]["authors"]),
        "WORK_WINDOW": (f"blocks {d['work_lo']:,}–{d['work_hi']:,}".replace(",", " ")
                        if d["work_hi"] else "no blocks collected yet"),
    }
    for k, v in repl.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    left = [m for m in ("{{",) if m in tpl]
    if left:
        import re
        raise SystemExit("unfilled placeholders: " + ", ".join(set(re.findall(r"\{\{(\w+)\}\}", tpl))))
    return tpl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--serve", action="store_true")
    a = ap.parse_args()

    db = database.connect(a.db or database.DEFAULT_DB)
    try:
        d = gather(db)
    finally:
        db.close()

    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "index.html").write_text(render(d), encoding="utf-8")
    src = ROOT / "research" / "proto" / "methodology.html"
    if src.exists():
        (DIST / "methodology.html").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"era {d['era_now']}, {len(d['V'])} validators, "
          f"N_eff stake {d['neff_stake']}, work {d['neff_work']}")
    print(f"written to {DIST}")

    if a.serve:
        import functools, http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(DIST))
        print("serving on http://127.0.0.1:8000")
        http.server.HTTPServer(("127.0.0.1", 8000), handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
