"""SQLite access. One file, one schema, no ORM.

u128 amounts are stored as TEXT: SQLite integers are 64-bit and a total stake
of 4.19e21 does not fit, while REAL would lose precision. All arithmetic on
these values is integer arithmetic in Python.
"""
from __future__ import annotations
import pathlib
import sqlite3

SCHEMA = pathlib.Path(__file__).with_name("schema.sql")
DEFAULT_DB = pathlib.Path(__file__).parents[1] / "data" / "holt.db"


def connect(path: pathlib.Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """Open the database, creating it and its schema if absent."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA.read_text())
    return db


def meta_get(db: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = db.execute("select value from meta where key = ?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("insert or replace into meta(key, value) values (?, ?)", (key, str(value)))


def eras_present(db: sqlite3.Connection) -> set[int]:
    """Eras that already have validator rows. Used to skip work on re-runs."""
    return {r[0] for r in db.execute("select distinct era from era_validators")}


def era_total_stake(db: sqlite3.Connection, era: int) -> int | None:
    row = db.execute("select total_stake from eras where era = ?", (era,)).fetchone()
    return int(row["total_stake"]) if row else None
