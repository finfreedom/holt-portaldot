"""S1 tests. Four of these exist because the specification names them as
done-criteria, and two of those four are security criteria.
"""
import pathlib
import sqlite3
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from engine import db as database          # noqa: E402
from engine.chain import EraSnapshot       # noqa: E402
from engine.config import ZERO_ACCOUNT     # noqa: E402
from engine.sync import SanityError, check_sanity, write_era   # noqa: E402

A = "5CtnsMuscb2qYfExampleAddressForTestsOnly000000001"
B = "5DHWWSGrhRgv9MExampleAddressForTestsOnly000000002"


def snap(era, total_stake, validators=None, nominations=None):
    return EraSnapshot(
        era=era, total_stake=total_stake, validator_reward=None, total_points=100,
        validators=validators if validators is not None else [{
            "address": A, "own": 10, "total": 1000, "nominator_count": 1,
            "commission_bp": 2600, "reward_points": 71, "is_active": 1}],
        nominations=nominations if nominations is not None else [
            {"nominator": B, "validator": A, "amount": 990}],
        active={A},
    )


@pytest.fixture
def db(tmp_path):
    conn = database.connect(tmp_path / "t.db")
    yield conn
    conn.close()


def test_rerun_is_idempotent(db):
    """A second pass over the same era repairs rows, it does not duplicate
    them. Without this a restarted sync silently doubles every exposure."""
    for _ in range(3):
        write_era(db, snap(100, 1000))
    db.commit()
    assert db.execute("select count(*) from era_validators where era=100").fetchone()[0] == 1
    assert db.execute("select count(*) from era_nominations where era=100").fetchone()[0] == 1
    assert db.execute("select count(*) from eras").fetchone()[0] == 1


def test_exposure_is_parsed_and_stored_exactly(db):
    """u128 survives the round trip. Stored as TEXT because SQLite integers
    are 64-bit; 4.19e21 does not fit and REAL would round it."""
    big = 4_194_640_029_197_252_300_000
    write_era(db, snap(101, big, validators=[{
        "address": A, "own": 1, "total": big, "nominator_count": 121,
        "commission_bp": 2600, "reward_points": 71, "is_active": 1}],
        nominations=[]))
    db.commit()
    row = db.execute("select total, nominator_count from era_validators"
                     " where era=101").fetchone()
    assert int(row["total"]) == big
    assert row["nominator_count"] == 121


def test_zero_account_never_enters(db):
    """The chain credits block production to an all-zero public key. It is not
    a validator, and the one door it could enter through is closed here."""
    write_era(db, snap(102, 1000, validators=[{
        "address": ZERO_ACCOUNT, "own": 0, "total": 0, "nominator_count": 0,
        "commission_bp": 0, "reward_points": 9, "is_active": 0}],
        nominations=[{"nominator": ZERO_ACCOUNT, "validator": A, "amount": 5}]))
    db.commit()
    assert db.execute("select count(*) from era_validators"
                      " where address=?", (ZERO_ACCOUNT,)).fetchone()[0] == 0
    assert db.execute("select count(*) from era_nominations"
                      " where nominator=?", (ZERO_ACCOUNT,)).fetchone()[0] == 0


def test_sanity_bound_halts_on_impossible_jump(db):
    """Security criterion. Total stake moving by orders of magnitude in one
    era means we are reading something wrong; recording it quietly would put
    a false number on a page that claims every figure is measured."""
    write_era(db, snap(200, 1_000_000))
    db.commit()
    with pytest.raises(SanityError):
        check_sanity(db, snap(201, 1_000_000 * 50))


def test_sanity_bound_allows_the_real_era_3873_event(db):
    """Security criterion, the other half. In era 3873 the largest validator
    left the set and total stake genuinely fell 7.9x. A bound that rejects
    real history is a bound that will be switched off."""
    write_era(db, snap(300, 4_194_595_210))
    db.commit()
    check_sanity(db, snap(301, 528_753_626))      # must not raise


def test_unfinalised_block_is_never_written():
    """Security criterion. Indexing an unfinalised head would record history
    that a reorg can erase. The guard is in Chain.is_finalised, which sync
    consults before reading anything."""
    from engine.chain import Chain
    probe = Chain.__new__(Chain)                 # no RPC connection
    probe.finalised_number = lambda: 1000        # type: ignore[method-assign]
    assert Chain.is_finalised(probe, 999) is True
    assert Chain.is_finalised(probe, 1000) is True
    assert Chain.is_finalised(probe, 1001) is False
