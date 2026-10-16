"""S4 tests. The root is the product's whole claim to verifiability, so these
test the format itself, not just that the code runs."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from engine import db as database                                   # noqa: E402
from engine.attest import attest, config_hash                       # noqa: E402
from engine.chain import EraSnapshot                                # noqa: E402
from engine.config import DEFAULT, Config, Weights                  # noqa: E402
from engine.merkle import (DOMAIN_NODE, DOMAIN_VALIDATOR, build_root,  # noqa: E402
                           config_leaf, h, validator_leaf)
from engine.score import FactorValue, Score, score_era              # noqa: E402
from engine.sync import write_era                                   # noqa: E402

A = "5AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
B = "5BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


@pytest.fixture
def db(tmp_path):
    conn = database.connect(tmp_path / "t.db")
    write_era(conn, EraSnapshot(
        era=1, total_stake=2000, validator_reward=None, total_points=200,
        validators=[
            {"address": A, "own": 10, "total": 1000, "nominator_count": 1,
             "commission_bp": 2600, "reward_points": 100, "is_active": 1},
            {"address": B, "own": 900, "total": 1000, "nominator_count": 1,
             "commission_bp": 3000, "reward_points": 100, "is_active": 1}],
        nominations=[], active={A, B}))
    conn.execute("update validators set pubkey = ? where address = ?", (b"\x01" * 32, A))
    conn.execute("update validators set pubkey = ? where address = ?", (b"\x02" * 32, B))
    conn.commit()
    yield conn
    conn.close()


def test_root_is_stable_across_runs(db):
    assert attest(db, 1)["root"] == attest(db, 1)["root"]


def test_changing_a_weight_changes_the_root(db):
    """The config version is part of the root by design: if a weight could be
    changed without the root moving, the attestation would prove nothing."""
    base = attest(db, 1)["root"]
    other = Config(weights=Weights(commission=3000, self_stake=3500,
                                   offences=2500, identity=1000))
    assert attest(db, 1, other)["root"] != base
    assert config_hash(other) != config_hash(DEFAULT)


def test_a_leaf_cannot_be_passed_off_as_a_node(db):
    """Domain separation. Without distinct prefixes an attacker could present
    an internal node as a validator leaf and claim a score that was never
    committed."""
    s = Score(address=A, score_bp=5000, gated=False, gate_reason=None,
              factors=[FactorValue("commission", 1, 0, 5000, 4000, True)])
    leaf = validator_leaf(b"\x01" * 32, s)
    node = h(DOMAIN_NODE, leaf, leaf)
    forged = h(DOMAIN_VALIDATOR, leaf, leaf)
    assert node != forged


def test_odd_level_duplicates_the_last_node():
    a, b, c = (bytes([i]) * 32 for i in (1, 2, 3))
    expected = h(DOMAIN_NODE,
                 h(DOMAIN_NODE, a, b),
                 h(DOMAIN_NODE, c, c))
    assert build_root([a, b, c]) == expected


def test_leaves_are_ordered_by_public_key_not_by_address(db):
    """Canonical order is the raw 32-byte key ascending. Sorting by SS58 text
    would give a different tree for the same data."""
    out = attest(db, 1)
    assert out["root"] == attest(db, 1)["root"]
    # A has pubkey 0x01…, B has 0x02…, while SS58 text sorts A before B too —
    # so assert on the mechanism rather than on a coincidence.
    s = score_era(db, 1)
    keys = {A: b"\x02" * 32, B: b"\x01" * 32}       # deliberately reversed
    from engine.merkle import era_root
    swapped = era_root(s, keys, DEFAULT.canonical()).hex()
    assert swapped != out["root"]


def test_inactive_factor_is_hashed_with_zero_weight_not_omitted(db):
    """Dropping an inactive factor would make two different configurations
    hash alike, which is exactly what the root must prevent."""
    scores = score_era(db, 1)
    identity = [f for s in scores for f in s.factors if f.name == "identity"]
    assert identity and all(not f.active for f in identity)
    assert all(f.weight_bp == 0 for f in identity)
    # it is still present in every leaf. The count comes from the config so
    # that adding a factor does not quietly make this assertion vacuous.
    expected = len(DEFAULT.canonical()["weights"])
    assert all(len(s.factors) == expected for s in scores)


def test_config_leaf_is_order_independent():
    """Canonical JSON: key order in the source dict must not change the hash."""
    one = config_leaf({"b": 2, "a": 1})
    two = config_leaf({"a": 1, "b": 2})
    assert one == two
