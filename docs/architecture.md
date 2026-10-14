# Architecture

Six stages. Each produces something that works on its own, so that an
unfinished later stage never invalidates an earlier one.

```
chain ──> sync ──> SQLite ──> score ──┬──> web
                                      ├──> attest ──> ink! contract (V3)
                                      └──> nominate ──> pool (V3)
                                                         │
                                            stPOT ───────┘  Assets pallet
```

---

## S1 · sync — reading

Finalised blocks only. Pulls eras into SQLite: validators, per-era exposure,
delegations, offences, block authors.

Nine tables. `u128` amounts are stored as `TEXT`, because SQLite integers are
64-bit and a stake of 4.19 × 10²¹ does not fit. Every write is idempotent on
`(era, address)` so a re-run repairs rather than duplicates.

Runs on a schedule because `historyDepth` is 84 eras: every day not collected
is a day permanently lost from an ordinary query.

**Done when** a re-run over the same range changes no rows, and the zero
account is filtered out.

## S2 · score — ranking

Pure functions over the database, no state. Weights in config, not code.
Factors, normalisation, the gate and the determinism contract are specified in
`methodology.md`.

**Done when** two runs produce byte-identical output, a factor with no spread
reports as inactive rather than uniform, and a gated validator shows a dash
instead of a score.

## S3 · web — the public surface

Two pages, no login required:

- **`/`** — network health, the eleven validators with scores and factor
  disclosure, the concentration figure, era history to the memory boundary.
- **`/methodology`** — the text of `methodology.md`, the attestation format,
  and the current root.

Mandatory, not optional: a table alternative for every chart, direct labels
alongside any colour encoding, a validated palette on both surfaces, and no
dual-axis charts anywhere.

## S4 · attest — fixing the scores on chain

A deliberately small ink! contract: `commit(era, root, engine_version)`,
owner-only. Small because the mainnet pallet is from 2021 and every line costs
toolchain pain; the contract targets V3, where the toolchain is current.

**Done when** the root computed by two independent implementations matches the
one in the contract, and a non-owner `commit` is rejected by test.

## S5 · nominate — submitting a target set

Two branches, and neither signs for a user.

*mainnet, read-only.* Computes the target set and prepares the
`staking.nominate` call without signing it. The plan is checkable: allocation
is deterministic and the scores are rooted on chain, so anyone can recompute
the set from the published root.

*V3, pool.* Creates a pool, drops `root` from itself, keeps `nominator`, and
submits the set. Real nomination with test tokens, with the permission
boundary enforced by the pallet.

**Done when** `--dry-run` prints a decision and sends nothing, the pool exists
with `root` provably not ours, and a test confirms the engine refuses to
submit a set containing a gated validator.

**First action in this stage:** one transaction that creates a pool and
nominates. Not an interface — a transaction. `NominationPools` is unproven on
Portaldot's build, and finding that out should cost one transaction rather
than a milestone.

## S6 · stPOT — the liquid receipt

A native `Assets` asset, not a Solidity contract. V3 has no precompile that
would let a contract reach a nomination pool, so an ERC-20 wrapper cannot see
the position it claims to represent.

```
assets.create(...)          the stPOT asset
assets.mint(to, amount)     against a pool contribution
assets.burn(from, amount)   on redemption
```

Exchange rate, not rebase: fewer moving parts and a smaller surface for error.
The rate tracks pool `points`, which is where reward actually accrues — not
the nominal deposit.

This is also the only part of the product with an official example from the
Portaldot team, and `freeze`, `approve` and `transfer_approved` already exist
in the pallet.

**Last on purpose.** It is the only stage that depends on someone else's
infrastructure. S1–S4 constitute a complete product without it.

---

## Why this order

Liquid staking is the headline; the risk engine is the build order. If V3
slips, "scoring first" still leaves a product — the analysis of a real network
with its numbers fixed on chain. "Liquid staking first" would leave nothing.
