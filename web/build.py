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
from engine.merkle import era_root          # noqa: E402
from engine.nominate import plan            # noqa: E402

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
    # The root is recomputed here rather than quoted. A page that spells out
    # a hash it did not derive is a page that goes stale the first time a
    # weight moves — and the whole claim is that moving a weight moves this.
    keys = dict(db.execute(
        "select address, pubkey from validators where pubkey is not null"))
    era_hash = era_root(score_era(db, era_now, DEFAULT), keys,
                        DEFAULT.canonical()).hex()
    noms = {r["validator"]: r["c"] for r in db.execute(
        "select validator, count(*) c from era_nominations where era = ? group by validator",
        (era_now,))}
    offences = {r["address"]: r["c"] for r in db.execute(
        "select address, count(*) c from offences group by address")}

    # Authors in the block window who are no longer in the validator set.
    # Their blocks are why the strip's total and the work denominator differ,
    # and they are the plainest statement of what consistency measures: a
    # validator can stop being there, and its delegators simply stop earning.
    in_set = {r["address"] for r in rows}
    gone = []
    for addr, blocks in sorted(work.items(), key=lambda kv: -kv[1]):
        if addr in in_set:
            continue
        seen = db.execute(
            """select era, total, commission_bp, nominator_count
                 from era_validators where address = ?
                order by era desc limit 1""", (addr,)).fetchone()
        if not seen:
            continue
        then_total = db.execute(
            "select sum(total) from era_validators where era = ?",
            (seen["era"],)).fetchone()[0]
        gone.append({
            "a": addr[:12], "b": blocks, "last": seen["era"],
            "missed": era_now - seen["era"],
            # Last known, not current: the account is not in the set now, so
            # there is no current figure to show. Saying when they were true
            # is the difference between a record and a wrong number.
            "s": round(int(seen["total"]) / int(then_total) * 100, 2)
                 if then_total else 0,
            "c": seen["commission_bp"] / 100,
            "n": seen["nominator_count"],
            "o": db.execute("select count(*) from offences where address = ?",
                            (addr,)).fetchone()[0],
        })

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
    band, by_era = [], {}
    for (e,) in db.execute("select distinct era from era_validators order by era"):
        xs = [int(x[0]) for x in db.execute(
            "select total from era_validators where era = ?", (e,))]
        if sum(xs):
            v = round(neff(xs), 4)
            band.append(v)
            by_era[e] = {"neff": v, "n": len(xs), "stake": sum(xs)}

    # The most notable era in the archive, found rather than remembered.
    # A page that names one frozen anecdote goes quietly wrong the moment
    # something bigger happens.
    median = sorted(band)[len(band) // 2] if band else 0
    event = max(by_era.items(), key=lambda kv: abs(kv[1]["neff"] - median),
                default=(None, None))

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
        "root": era_hash,
        # Full addresses and raw values, for prose that names an account.
        "V_full": [{"full": r["address"],
                    "sc_raw": scores[r["address"]].score_bp,
                    "s_bp": (int(r["total"]) * 10_000 // total) if total else 0}
                   for r in rows],
        "factor_rows": factor_rows(score_era(db, era_now, DEFAULT)),
        "factor_sum": factor_sum(score_era(db, era_now, DEFAULT)),
        "plan": plan(db, era_now, DEFAULT),
        "n_offences": db.execute("select count(*) from offences").fetchone()[0],
        "block": head, "V": V, "seq": seq,
        "neff_stake": round(neff(stake), 2),
        "neff_work": round(neff(list(work.values())), 2) if work else 0,
        "top_stake": V[0]["s"] if V else 0,
        "top_work": V[0]["w"] if V else 0,
        "gone": gone,
        "busiest": max((v["b"] for v in V), default=0),
        "quietest": min((v["b"] for v in V if v["b"]), default=0),
        "band_min": min(band) if band else 0, "band_max": max(band) if band else 0,
        "counts": counts,
        # Work and stake come from different samples: stake is an era
        # snapshot, work is a window of blocks collected separately and
        # slowly. The window is labelled on the page, because two samples
        # shown side by side otherwise read as one.
        "work_lo": win["lo"] or 0, "work_hi": win["hi"] or 0,
        "event_era": event[0], "event": event[1], "by_era": by_era,
        "median_neff": median,
        "gated": [v for v in V if v["c"] >= 100],
    }


def event_text(d: dict) -> tuple[str, str, str]:
    """Describe the archive's most unusual era in its own numbers."""
    era, ev = d["event_era"], d["event"]
    if not ev:
        return ("No era stands out yet", "", "")
    before = d["by_era"].get(era - 1)
    after = d["by_era"].get(era + 1)
    if before and ev["n"] < before["n"]:
        title = "The largest validator was <i>not there</i>"
        drop = before["stake"] / ev["stake"] if ev["stake"] else 0
        body = (f"The set shrank from {before['n']} to {ev['n']}. Total stake fell "
                f"{drop:.1f}-fold, and effective decentralisation moved from "
                f"{before['neff']:.2f} to {ev['neff']:.2f}")
        body += (f". One era later it was back at {after['neff']:.2f}."
                 if after else ".")
    else:
        title = "The set moved further than usual"
        body = (f"Effective decentralisation reached {ev['neff']:.2f} against a "
                f"median of {d['median_neff']:.2f} across the archive, with "
                f"{ev['n']} validators in the set.")
    ago_s = ago((d["era_now"] - era) * BLOCKS_PER_ERA)
    return title, body, ago_s


def victims_text(d: dict) -> tuple[str, str]:
    """The gated validators, and whoever is still delegating to one."""
    gated = d["gated"]
    empty = sum(1 for v in gated if v["n"] == 0)
    withn = [v for v in gated if v["n"] > 0]
    words = {0: "No", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
    head = words.get(empty, str(empty))
    if not withn:
        return head, " Every one of them is left alone."
    worst = max(withn, key=lambda v: v["n"])
    return head, (f" {words.get(worst['n'], worst['n'])} accounts still delegate "
                  f"to {worst['a']}…, and the whole reward stays with it.")


# What each factor measures, in the reader's words. The weight and whether
# the factor is live are NOT here — those come from the config and from a
# live scoring run, so this page cannot claim a weight the engine does not
# use, or call a factor dead while it is deciding scores.
FACTOR_PROSE = {
    "1": ("Commission", "the rate itself; observed spread 25–100%"),
    "2": ("Self-stake", "<code>own/total</code>, on a log scale"),
    "3": ("Offences", "count of <code>Offences</code> records, on a log scale"),
    "4": ("Identity", "whether on-chain identity is filled in"),
    "6": ("Consistency", "share of archived eras spent in the active set"),
}
# Designed but not wired into the score. Kept visible so the page shows what
# was considered and rejected, not only what survived.
FACTOR_UNSCORED = [
    ("Liveness", "reward points against the median",
     "off", "does not separate — off"),
    ("Oversubscription",
     "headroom to <code>maxNominatorRewardedPerValidator</code> (256)",
     "off", "protective, fires as the set grows"),
    ("Commission jumps", "changes inside a window",
     "dead", "dead — none in 84 eras"),
]


def factor_rows(scores) -> str:
    """Build the factor table from the config and a live scoring run."""
    seen = {}
    for s in scores:
        for f in s.factors:
            seen.setdefault(f.name, f.active)
            seen[f.name] = seen[f.name] or f.active
    by_name = {FACTOR_PROSE[i][0].lower(): i for i in FACTOR_PROSE}
    weights = DEFAULT.canonical()["weights"]

    rows = []
    for fid, (name, prose) in FACTOR_PROSE.items():
        key = name.lower().replace("-", "_")
        active = seen.get(key, seen.get(name.lower(), False))
        w = weights[fid]
        if active:
            weight_cell = f'<td class="w">{w / 10000:.2f}</td>'
            state = "decisive" if w >= 3000 else "live"
            state_cell = f'<td class="l">{state}</td>'
        else:
            weight_cell = '<td class="off">—</td>'
            state_cell = '<td class="l off">does not separate — off</td>'
        rows.append(f'<tr><td>{name}</td>{weight_cell}'
                    f'<td class="l">{prose}</td>{state_cell}</tr>')
    for name, prose, cls, state in FACTOR_UNSCORED:
        rows.append(f'<tr><td>{name}</td><td class="off">—</td>'
                    f'<td class="l">{prose}</td>'
                    f'<td class="l {cls}">{state}</td></tr>')
    return "\n      ".join(rows)


WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}


def factor_sum(scores) -> str:
    """The total row. The live weights do not add to one — the switched-off
    factor's share is renormalised across the rest — so the row states the
    nominal total and says what happens to the remainder rather than
    printing a tidy 1.00 the column above does not support."""
    seen = {}
    for s in scores:
        for f in s.factors:
            seen[f.name] = seen.get(f.name, False) or f.active
    weights = DEFAULT.canonical()["weights"]
    live = {fid: w for fid, w in weights.items()
            if seen.get(FACTOR_PROSE[fid][0].lower().replace("-", "_"), False)}
    total = sum(live.values()) / 10000
    n = len(live)
    note = ("" if total == 1 else
            f"renormalised to 1.00 across the {WORDS.get(n, n).lower()}")
    return (f'<tr class="sum"><td>{WORDS.get(n, n)} carry the score</td>'
            f'<td class="w">{total:.2f}</td>'
            f'<td class="l">{note}</td><td class="l"></td></tr>')


def gone_text(d: dict) -> str:
    """One sentence about authors who have since left the set, or nothing."""
    gone = d.get("gone") or []
    if not gone:
        return ("Every account that produced a block in this window is still "
                "in the set.")
    g = gone[0]
    rest = (f" Two others left as well." if len(gone) == 3 else
            f" {len(gone) - 1} others left as well." if len(gone) > 2 else
            " One other left as well." if len(gone) == 2 else "")
    if g["missed"]:
        tail = (f"has not been in the set since era {g['last']}, "
                f"{g['missed']} eras ago. Anyone still delegating to it has "
                f"earned nothing for every one of them.")
    else:
        tail = "is no longer in the set."
    return (f"The strip counts the current set. The window also holds "
            f"{g['b']} blocks from {g['a']}…, which {tail}{rest}")


def plan_rows(p) -> str:
    return "\n      ".join(
        f'<tr><td>{t.address[:12]}…</td>'
        f'<td>{t.score_bp / 100:.1f}</td>'
        f'<td>{t.stake_share_bp / 100:.2f}%</td>'
        f'<td class="l">{t.reason}</td></tr>'
        for t in p.targets)


WORDS_N = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}


def plan_excluded(p, scores, shares) -> str:
    """Why each declined validator was declined. An omission with no reason
    attached is indistinguishable from an oversight — and the two reasons
    here are different in kind, so they are not run together."""
    out = []
    if p.excluded_gated:
        n = len(p.excluded_gated)
        word = WORDS_N.get(n, str(n)).lower()
        verb = "takes" if n == 1 else "take"
        out.append(f"{word.capitalize()} {verb} 100% commission, which "
                   f"returns a delegator nothing.")
    for addr in p.excluded_oversized:
        sc = scores.get(addr)
        out.append(
            f"{addr[:12]}… is declined for a different reason: it scores "
            f"{sc / 100:.1f} on its own conduct, which is a real score, but "
            f"it already holds {shares.get(addr, 0) / 100:.2f}% of the "
            f"network. Scoring asks whether a validator is sound; allocation "
            f"asks where the stake should go.")
    return " ".join(out) if out else "Nothing was declined."


def plan_call(p) -> str:
    """The extrinsic, as it would be submitted — by the nominator, not us."""
    inner = ",\n    ".join(f'"{t.address}"' for t in p.targets)
    return (f'Staking.nominate({{\n  targets: [\n    {inner}\n  ]\n}})')


def render(d: dict) -> str:
    tpl = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    boundary = d["era_now"] - HISTORY_DEPTH + 1
    ev_title, ev_body, ev_ago = event_text(d)
    g_empty, g_sentence = victims_text(d)
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
        "ROOT_SHORT": d["root"][:32] + "…",
        "N_SCORED": str(len(d["V"])),
        "N_BLOCKS": f"{len(d['seq']):,}".replace(",", " "),
        "GONE": gone_text(d),
        "GONE_ROWS": json.dumps(d.get("gone") or [], separators=(",", ":")),
        "PLAN_ROWS": plan_rows(d["plan"]),
        "PLAN_N": str(len(d["plan"].targets)),
        "PLAN_NEFF": f"{d['plan'].neff_portfolio:.2f}",
        "PLAN_CALL": plan_call(d["plan"]),
        "PLAN_EXCLUDED": plan_excluded(
            d["plan"],
            {v["full"]: v["sc_raw"] for v in d["V_full"]},
            {v["full"]: v["s_bp"] for v in d["V_full"]}),
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
        "EVENT_ERA": str(d["event_era"] or "—"),
        "EVENT_AGO": ev_ago,
        "EVENT_TITLE": ev_title,
        "EVENT_BODY": ev_body,
        "GATED_EMPTY": g_empty,
        "VICTIMS_SENTENCE": g_sentence,
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
        page = src.read_text(encoding="utf-8")
        page = page.replace("{{FACTOR_ROWS}}", d["factor_rows"])
        page = page.replace("{{FACTOR_SUM}}", d["factor_sum"])
        page = page.replace("{{N_OFFENCES}}", f"{d['n_offences']:,}".replace(",", " "))
        left = [m for m in ("{{",) if m in page]
        if left:
            raise SystemExit("methodology.html: a placeholder was left unfilled")
        (DIST / "methodology.html").write_text(page, encoding="utf-8")

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
