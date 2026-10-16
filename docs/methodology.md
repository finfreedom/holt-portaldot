# Methodology

How a validator score is computed, and how to check we computed it that way.

---

## Factors

Nine were designed. On this network five separate validators and four return
the same answer for everyone; those are switched off rather than carried as
decoration. Which group a factor sits in is measured per run, not decided
once — consistency moved from the second group to the first as the archive
deepened. The weights in the table below are checked against the engine's
own config by `check.py`, so this page cannot drift away from the code that
produced the root.

| Factor | id | Weight | Measures | State |
|---|---|---|---|---|
| Commission | 1 | 0.35 | the rate; observed spread 25–100% | decisive |
| Self-stake | 2 | 0.20 | `own/total`, log scale | live |
| Offences | 3 | 0.20 | count of `Offences` records, log scale | live |
| Identity | 4 | 0.05 | whether on-chain identity is set | does not separate |
| Liveness | 5 | — | reward points against the median | does not separate |
| Consistency | 6 | 0.20 | share of archived eras in the active set | live, absolute |
| Oversubscription | 7 | — | headroom to `maxNominatorRewardedPerValidator` (256) | protective |
| Commission jumps | — | — | changes within a window | dead: none in 84 eras |

### Absolute and relative factors

Most factors are read against the set: the point of a commission figure is
whether it beats the alternatives, so the observed range maps onto 0–1.

Consistency is not like that. It is a share of eras, and 98% means 98%
whichever company it keeps. Stretching it across the set would score a
validator present in 111 eras out of 113 at a flat zero for the sole reason
that the other nine missed nothing — which is what the first implementation
did, and what the test named
`test_consistency_is_absolute_not_stretched` now prevents. Absolute factors
are used as measured.

Consistency also carries a depth condition: below 28 archived eras (14 days)
it switches off. On a short archive everyone is present in every era, and
that reports how briefly we have watched rather than how reliable anyone is.

**A factor with no spread contributes zero, not "the same to everyone."**
Values normalise against the observed range; when that range is empty the
factor switches off and the remaining weights renormalise. The interface says
"does not separate" beside it. That is more honest than performing analysis
where there is none, and it explains why the score rests on four columns of the five
that carry weight.

Factor ids are permanent and never reused, because they are hashed.

## The gate

A validator charging 100% commission is excluded: a nominator delegating to it
receives exactly nothing. The gate suppresses **the displayed score as well**,
not only participation in the allocation.

Without that, such a validator scores well on self-stake — often 100% of its
own — and lands above the largest validator in the table. A reader takes that
ordering as a recommendation. Gated validators appear in a separate list with
the reason stated.

## Scoring and allocation are separate

Scoring answers *is this validator sound?* and knows nothing about
concentration. A large validator charging 26% and producing blocks reliably is
a fine choice for an individual; docking its score for other people's
delegations would be dishonest.

Allocation answers *where should this stake go?* and that is where a
per-validator cap applies. Both are shown: that the validator is sound, and why
it is not given everything.

A nominator submits a **list of targets** and nothing else — Phragmén decides
the proportions. The published figure is therefore what the election returns,
and the drift between intent and outcome is shown afterwards from
`erasStakers`.

---

## Determinism

Two runs over the same era must produce identical bytes on any machine, or the
attestation below is worthless.

- **Inputs are the chain and the config, nothing else.** No wall clock, no
  randomness, no network state beyond the finalised snapshot of that era.
- **Integer arithmetic throughout.** Values are basis points — `u16`, 0 to
  10 000. Never floating point. Division truncates, and the truncation is part
  of the specification.
- **Canonical ordering.** Validators by raw public key ascending; factors by id.
- **The config version is part of the result.** Change a weight, change the root.

```
value_bp = (raw − min) × 10000 // (max − min)    inverted where lower is better
         = inactive                               when max == min

score_bp = Σ(weight_i × value_bp_i) // Σ(weight_i)   over active factors only
```

---

## Attestation format

`blake2-256` everywhere, big-endian numbers, every hash domain-separated so a
leaf can never be passed off as a node.

```
leaf_i = blake2_256(
    "holt.v1.validator"
  ‖ account_id        32 bytes, raw public key
  ‖ score_bp          u16
  ‖ gated             u8, 1 if excluded by the gate
  ‖ factors_hash      32 bytes
)

factors_hash = blake2_256(
    "holt.v1.factors"
  ‖ for each factor, ascending factor_id:
    factor_id  u8
  ‖ value_bp   u16
  ‖ weight_bp  u16, zero if the factor is off
  ‖ active     u8
)

leaf_0 = blake2_256("holt.v1.config" ‖ canonical_config_bytes)

node   = blake2_256("holt.v1.node" ‖ left ‖ right)
```

Binary tree. Leaves in canonical order: `leaf_0` first, then validators by
ascending public key. An odd node duplicates the last.

On chain, one call:

```
commit(era: u32, root: [u8;32], engine_version: u32)
```

Owner-only, fixed at instantiation. There is no second way to write a root.

---

## Verifying us

1. Take the era snapshot from the public chain.
2. Take the published config — weights live there, not in code.
3. Recompute leaves and root by the description above.
4. Compare with the root in the contract.

A mismatch means we displayed something other than what we committed.

```
scoring root, era 3863
4f3446da82ab111568328a63f8537101e666ecae6664c0865cd390c9a80d4700
```

Two implementations, Python and TypeScript, were written against this written
format and produced that root independently. One implementation proves the code
agrees with itself; two prove the **specification** is complete.

---

## Key handling

- A single module touches private keys. Nothing else imports it.
- The signing key comes from `HOLT_SIGNER_URI` in the environment and from
  nowhere else. Absent it, the engine runs `--dry-run` and refuses to sign.
- The key never reaches logs, error text, tracebacks or serialisation —
  enforced by test, not by discipline.
- No key exists in this repository in any form, at any point in its history.
- The agent key is not the owner key. It holds fee money only.

---

## Naming

Offences are offences, never slashes. `staking.unappliedSlashes` is empty and
every recorded slash fraction is zero: all 407 records are unresponsiveness
signals from `ImOnline`. Calling them slashes in an interface would be a lie.
