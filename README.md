# Holt

**Delegation risk for Portaldot.** Holt reads the chain, scores validators on
what can be measured, and publishes both the scores and a merkle root of them
so the numbers cannot be changed after the fact.

It holds no authority over anyone's stake.

---

## It got worse in the week before this repository existed

The archive has been collecting since 30 September. Between era 3876 and
era 3890 — seven days — the network lost a validator:

```
                    era 3876        era 3890
  validators              11              10
  N_eff by stake        1.30            1.14
  largest share       87.39%          93.66%
```

The one that left, `5DHWWSGrhRgv9M…`, was the **second largest**: 6.71% of
stake, seven delegators, 26% commission. It was one of the few targets that
passed the gate and offered real diversification.

The chain's staking pallet answers from era 3806. The archive holds from 3780,
twenty-six eras deeper, which is the only reason that comparison can be made
at all.

---

## The finding this was built around

Portaldot has eleven validators. Counted by the work they do, the network
behaves like **10.88** of them. Counted by the money they hold, it behaves
like **1.30**.

```
                     spread        N_eff
  blocks produced     1.46×        10.88
  stake held          1456×         1.30
```

One account holds **87.39%** of all stake and produced **9.86%** of the blocks
in era 3876 — second place. Two validators holding roughly two per cent each
produced more than it did.

Both figures are the inverse Herfindahl index over the same eleven accounts.
Work is shared almost evenly; money is not shared at all.

Every number here was read from `wss://mainnet.portaldot.io` over finalised
blocks. Block authors come from the BABE pre-runtime digest of all 720 headers
in the era — `Authorship.Author` does not resolve on this runtime.

---

## What works today

| | |
|---|---|
| **Archive** | 97 eras, 1 066 validator records, 13 774 delegations, 407 offences, 720 block headers |
| **Scoring** | four factors that separate validators on this network, five that do not and are switched off |
| **Attestation** | byte-exact merkle format, two independent implementations agreeing on the root |
| **Reading** | mainnet only, finalised blocks only, no signing |

## What does not work yet

- **The pool on V3 is unproven.** Portaldot's developer guide does not cover
  staking at all; the V3 testnet runs one validator and zero pools. The first
  thing we do there is one transaction that creates a pool and nominates,
  before any interface is built on it.
- **No live nomination anywhere.** By choice, not by omission — see Security.
- **stPOT, the liquid receipt, is designed and not built.** It will be a
  native `Assets` asset rather than a Solidity contract, because V3 has no
  precompile that would let a contract reach a pool. The asset stays visible
  from EVM and MetaMask through the `Assets` precompile. Exchange rate tracks
  pool points, not the nominal deposit.
- **Correlated-failure clusters were the original thesis and were not found.**
  An early run appeared to find them; it had grouped by payout *variant*
  instead of payout *address*. The finding was withdrawn. What replaced it is
  the concentration figure above.

---

## Security: we hold nothing

Holt takes no custody and no delegated authority, on any network.

On **mainnet** it reads. It computes a target set and publishes it; it never
signs on anyone's behalf. There is no proxy, no agent key with authority over
a stake, and therefore nothing to steal.

On **V3** it operates a nomination pool holding only the `nominator` role.
That boundary is enforced by the pallet, not by our discipline:

```rust
can_nominate(who)           is_root(who) || roles.nominator == who
can_update_roles(who)       is_root(who)          // not us
can_manage_commission(who)  is_root(who)          // not us
can_toggle_state(who)       is_root || is_bouncer // not us
```

A stolen agent key can submit a worse set of nominations. It cannot reach
funds, commission, roles, or membership. The pool's bonded account is keyless.

**Why not a proxy.** `ProxyType::Staking` on Portaldot's runtime admits the
whole of `pallet_staking`, including `set_payee(Account(...))` — redirection of
every future reward. A delayed proxy closes it, but only as long as someone
watches the announcements. We removed the mechanism instead of defending it.

**Why not `DelegatedStaking`.** The pallet is present on V3 but exposes no
dispatchables: it has no `#[pallet::call]` block at all. Its functions take
`OriginFor<T>` and sit in a plain `impl`. Checked in the upstream source, to be
re-checked against their fork when the node returns.

---

## Verifying us

Nothing below needs our cooperation.

1. Take the era snapshot from the public chain.
2. Take the published config — weights live there, not in code.
3. Recompute leaves and root by `docs/methodology.md`.
4. Compare with the root in the attestation contract.

A mismatch means we displayed something other than what we committed.

```
scoring root, era 3863
172cde2268727de2a0df6215fab70cb0accf48bcb91d910464d81722e3655523
```

Two implementations — Python and TypeScript — were written against the written
format and produced that root independently. One implementation proves the code
agrees with itself; two prove the *specification* is complete.

---

## Running it

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m engine.sync          # pull finalised eras into SQLite
.venv/bin/python -m engine.score  --era N
.venv/bin/python -m engine.attest --era N --dry-run
```

`--dry-run` is the default everywhere that signs. Without `HOLT_SIGNER_URI` in
the environment the engine refuses to sign at all; there is no key in this
repository, in any file, at any point in its history.

---

## What we found out about Portaldot along the way

Published because nobody had written it down, and the next person should not
have to measure it again.

- `pallet-contracts` on mainnet reports `palletVersion 0` — Substrate 3.0,
  February 2021. Only ink! `3.0.0-rc3` with `cargo-contract 0.12.1` builds for
  it, on a nightly from roughly August 2021. Full recipe and working lockfiles:
  **[portaldot-ink-toolchain](https://github.com/finfreedom/portaldot-ink-toolchain)**
- V3 is a different story entirely: `palletVersion 16` plus `pallet-revive`.
  Modern ink! 5 and stable Rust. Artifacts for the two networks are mutually
  incompatible at the host-function level.
- `py-substrate-interface` needs `type_registry_preset="legacy"` for mainnet.
  The preset named in their documentation does not exist.
- V3 exposes precompiles for `Assets` and `Vesting` only. There is none for
  staking or pools, so a Solidity contract cannot reach a nomination pool.
- The staking pallet forgets after 84 eras — forty-two days. Their RPC happens
  to run as an archive node, so historical state still answers; that is a
  retention policy, not a guarantee.
- Roughly 1.3% of block production is attributed to an account with an
  all-zero public key. Reported separately.

---

## Layout

```
engine/     reading, scoring, attestation — Python, SQLite
contracts/  ink! attestation contract
web/        the dashboard and the methodology page
docs/       methodology, architecture, security, measurements, findings
```

Offences are called offences, never slashes. `staking.unappliedSlashes` is
empty and every recorded slash fraction is zero: all 407 are unresponsiveness
signals from `ImOnline`. Naming them slashes in an interface would be a lie.
