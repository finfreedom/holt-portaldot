"""The plan must never recommend what the product warns about."""
import pytest

from engine import db as database
from engine.config import DEFAULT
from engine.nominate import plan
from engine.sync import write_era
from engine.chain import EraSnapshot

A = "5CtnsMuscb2qYfQpNcKbhiKt84DNWpXoNiMKZP5tFVsEEqxm"
B = "5ENZRaWjc4wrDYNnFBdSrpVuZhPcDbQVrPXYPTFQVPmYLbSe"
C = "5F4s9VGWseiYMfLJTdHQmTLLBqfGKRnXYYPNZpTxBfEFLRxF"
D = "5GUP3qMcdpAE5tJvHvKmPxmwUrmLaTKNBstYTvWcMvxXKKDe"


def val(addr, own, total, commission_bp, points=100):
    return {"address": addr, "own": own, "total": total, "nominator_count": 1,
            "commission_bp": commission_bp, "reward_points": points,
            "is_active": 1}


@pytest.fixture
def db(tmp_path):
    conn = database.connect(tmp_path / "t.db")
    yield conn
    conn.close()


def seed(db, validators, era=1):
    write_era(db, EraSnapshot(
        era=era, total_stake=sum(v["total"] for v in validators),
        validator_reward=None, total_points=300, validators=validators,
        nominations=[], active={v["address"] for v in validators}))
    db.commit()


def test_gated_validators_never_appear_in_the_plan(db):
    """A hundred-per-cent commission returns the nominator nothing. Ranking
    it last would still present it as an option; it is not one."""
    seed(db, [val(A, 10, 100, 10_000), val(B, 20, 100, 3000),
              val(C, 30, 100, 2500), val(D, 40, 100, 2000)])
    p = plan(db, 1)
    assert A not in [t.address for t in p.targets]
    assert A in p.excluded_gated


def test_a_validator_over_the_cap_is_excluded_from_allocation(db):
    """Scoring and allocation are separate. An account holding most of the
    network is not misbehaving, so it scores normally — but sending it more
    stake is the thing this project exists to warn about."""
    seed(db, [val(A, 50, 9000, 2000),      # 90% of the network, best commission
              val(B, 20, 400, 3000),
              val(C, 30, 400, 2500),
              val(D, 40, 200, 2600)])
    p = plan(db, 1)
    assert A in p.excluded_oversized
    assert A not in [t.address for t in p.targets]
    assert all(t.stake_share_bp <= p.threshold_bp for t in p.targets)


def test_the_plan_is_deterministic(db):
    """Anyone holding the published root for an era must recompute the same
    set, or publishing the root proves nothing about the plan."""
    seed(db, [val(A, 10, 100, 2000), val(B, 20, 100, 3000),
              val(C, 30, 100, 2500), val(D, 40, 100, 2600)])
    first = plan(db, 1)
    second = plan(db, 1)
    assert [t.address for t in first.targets] == [t.address for t in second.targets]
    assert first.call == second.call


def test_the_plan_is_never_signed(db):
    """The one invariant that protects other people's money: this module
    produces a call to be read, never a transaction to be sent."""
    seed(db, [val(A, 10, 100, 2000), val(B, 20, 100, 3000)])
    p = plan(db, 1)
    assert p.call["call_module"] == "Staking"
    assert p.call["call_function"] == "nominate"
    assert set(p.call) == {"call_module", "call_function", "call_args"}
    assert "signature" not in p.call and "signer" not in p.call


def test_targets_never_exceed_the_chain_limit(db):
    """maxNominations is 16 on this runtime; a longer list is rejected."""
    many = [val(f"5{i:047d}", 10, 100, 2000 + i) for i in range(30)]
    seed(db, many)
    p = plan(db, 1)
    assert len(p.targets) <= DEFAULT.canonical()["max_targets"]


def test_reasons_distinguish_rather_than_repeat(db):
    """The first version returned 'lowest commission' for every entry,
    because commission carries the heaviest weight and everyone scored near
    the top of it. A reason shared by the whole list explains nothing."""
    seed(db, [val(B, 90, 100, 3000), val(C, 10, 100, 2000),
              val(D, 50, 100, 2500)])
    p = plan(db, 1)
    reasons = [t.reason for t in p.targets]
    assert len(set(reasons)) > 1, reasons


def test_a_small_even_network_is_not_emptied_by_the_cap(db):
    """Three validators holding a third each are not concentrated — they are
    three validators. A flat 25% cap excluded all of them and returned an
    empty plan, which is the wrong answer stated confidently."""
    seed(db, [val(B, 10, 100, 2000), val(C, 20, 100, 2500),
              val(D, 30, 100, 3000)])
    p = plan(db, 1)
    assert len(p.targets) == 3, p.excluded_oversized
    assert not p.excluded_oversized
