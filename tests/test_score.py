"""S2 tests. Three of these are the specification's done-criteria."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from engine import db as database                      # noqa: E402
from engine.chain import EraSnapshot                   # noqa: E402
from engine.score import normalise, score_era, summary # noqa: E402
from engine.sync import write_era                      # noqa: E402

A = "5AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
B = "5BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
C = "5CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"


def val(addr, own, total, commission_bp, points=100):
    return {"address": addr, "own": own, "total": total, "nominator_count": 1,
            "commission_bp": commission_bp, "reward_points": points, "is_active": 1}


@pytest.fixture
def db(tmp_path):
    conn = database.connect(tmp_path / "t.db")
    yield conn
    conn.close()


def seed(db, validators, era=1):
    write_era(db, EraSnapshot(era=era, total_stake=sum(v["total"] for v in validators),
                              validator_reward=None, total_points=300,
                              validators=validators, nominations=[],
                              active={v["address"] for v in validators}))
    db.commit()


def test_identical_runs_produce_identical_output(db):
    """Done-criterion. Without this the attestation root is worthless: two
    runs over the same era must agree byte for byte."""
    seed(db, [val(A, 10, 1000, 2600), val(B, 500, 1000, 3000),
              val(C, 1, 1000, 10_000)])
    a = score_era(db, 1)
    b = score_era(db, 1)
    assert [(s.address, s.score_bp, s.gated) for s in a] == \
           [(s.address, s.score_bp, s.gated) for s in b]
    assert [[(f.factor_id, f.value_bp, f.weight_bp, f.active) for f in s.factors]
            for s in a] == \
           [[(f.factor_id, f.value_bp, f.weight_bp, f.active) for f in s.factors]
            for s in b]


def test_factor_without_spread_reports_inactive_not_uniform(db):
    """Done-criterion. Every validator here has identity unset, so the factor
    separates nothing. It must say so and contribute zero — not hand the same
    points to everyone, which would look like analysis and be noise."""
    seed(db, [val(A, 10, 1000, 2600), val(B, 500, 1000, 3000)])
    scores = score_era(db, 1)
    identity = [f for s in scores for f in s.factors if f.name == "identity"]
    assert all(not f.active for f in identity)
    assert all(f.weight_bp == 0 for f in identity)
    assert all(f.value_bp == 0 for f in identity)
    assert "identity" in summary(scores)["inactive_factors"]


def test_gated_validator_has_no_score_at_all(db):
    """Done-criterion. A 100%-commission validator scores well on self-stake —
    it is usually 100% its own — and would sort above the largest validator in
    the table. A reader takes that ordering as a recommendation."""
    seed(db, [val(A, 10, 1000, 2600), val(B, 1000, 1000, 10_000)])
    scores = {s.address: s for s in score_era(db, 1)}
    assert scores[B].gated is True
    assert scores[B].score_bp == 0
    assert scores[B].gate_reason == "commission 100%"
    assert scores[A].gated is False


def test_weights_renormalise_when_a_factor_switches_off(db):
    """A validator that is best on every live factor must reach the top of the
    range, whatever share of the nominal weight those factors carry."""
    seed(db, [val(A, 1, 1000, 10_000 - 1), val(B, 1000, 1000, 1)])
    scores = {s.address: s for s in score_era(db, 1)}
    assert scores[B].score_bp == 10_000     # best commission and best self-stake
    assert scores[A].score_bp == 0


def test_lower_is_better_factors_are_inverted():
    """Commission and offences count against a validator; stake and identity
    count for it. Getting this backwards would invert the whole product."""
    raws = {A: 2600, B: 10_000}
    low_better = normalise(raws, higher_is_better=False)
    assert low_better[A] == 10_000 and low_better[B] == 0
    high_better = normalise(raws, higher_is_better=True)
    assert high_better[A] == 0 and high_better[B] == 10_000


def test_empty_range_returns_none():
    assert normalise({A: 5, B: 5}, higher_is_better=True) is None


def test_scores_come_back_in_canonical_order(db):
    """The merkle tree hashes leaves in ascending public key order, so the
    scorer must emit them that way or the root will not reproduce."""
    seed(db, [val(C, 1, 100, 2000), val(A, 1, 100, 3000), val(B, 1, 100, 4000)])
    assert [s.address for s in score_era(db, 1)] == sorted([A, B, C])
