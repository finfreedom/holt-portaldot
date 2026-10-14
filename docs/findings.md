# What we learned about Portaldot

Measured, not assumed. Dates are given because a number without a date becomes
a lie within a week. Everything here was read from the public chain or from
published source, and can be read again.

---

## The network, as of era 3876 (7 October 2026)

```
validators            11          target 15
nominators           152
staked                4.1%        of supply
block time            60 s        ExpectedBlockTime 60000
session              120 blocks   2 hours
era                  720 blocks   12 hours
pallet history        84 eras     42 days
bonding duration      60 eras     30 days
existential deposit    1 POT
genesis   0x83b5212c69f85f3996f8696bb35bf913af51b176a5f53d0a74fd3a83dc0b8a54
```

Sixty-second blocks are unusual for a Substrate chain — Polkadot produces one
every six. It matters for anything that tries to look live: a block-by-block
ticker on this network shows one event per minute and reads as broken.

---

## Work is shared; stake is not

Over the full 720 blocks of era 3876:

```
                     spread        N_eff
  blocks produced     1.46×        10.88
  stake held          1456×         1.30
```

The largest account holds 87.39% of stake and produced 71 blocks — 9.86%,
second place. `5FQzFfora2im…`, holding 2.43%, produced 83. Both figures are the
inverse Herfindahl index over the same eleven accounts.

The same account also carries **93 offence records**, an order of magnitude
more than any other validator in the set.

### Getting block authors

`Authorship.Author` does not resolve on this runtime. The author is in the
block header's BABE pre-runtime digest, as `authority_index` — an index into
`Session.Validators` at that block:

```python
hdr = s.get_block_header(block_hash=bh)
for log in hdr["header"]["digest"]["logs"]:
    pr = (log.value if hasattr(log, "value") else log).get("PreRuntime")
    if pr and isinstance(pr.get("data"), dict):
        idx = pr["data"].get("authority_index")
```

Roughly 1.8 s per block over a remote RPC, so one era takes about 21 minutes.
Validator sets change per session, so cache `Session.Validators` by session
rather than once.

---

## Contracts: two incompatible worlds

| | mainnet | V3 testnet |
|---|---|---|
| `contracts.palletVersion` | **0** | **16** |
| toolchain | `cargo-contract 0.12.1` | `cargo-contract 5.0.3` |
| ink! | `3.0.0-rc3` | `5.1.1` |
| compiler | nightly ≈ 2021-08-01 | stable 1.87 |
| pinned versions needed | 8 | none |
| metadata `.json` | **not generated** | generated |
| also present | — | `pallet-revive` (PolkaVM, Solidity) |

Mainnet runs `pallet-contracts 3.0.0` — Substrate 3.0, February 2021. The build
window is narrow at both ends: `ink_storage` needs the since-removed
`feature(const_generics)`, while edition 2021 only arrives in Rust 1.56.

**The trap that costs an evening:** without `-Z original-manifest`,
`cargo-contract` copies the project to a temporary directory and re-resolves
dependencies from scratch, ignoring your `Cargo.lock` entirely.

Artifacts are mutually incompatible at the host-function level. An ink! 5
contract imports `seal1 get_storage` and `seal2 set_storage`, which do not
exist in the mainnet pallet; `seal0` code will not load on pallet version 16.

Full recipe, working `Cargo.toml` and `Cargo.lock`:
**[portaldot-ink-toolchain](https://github.com/finfreedom/portaldot-ink-toolchain)**

At the time of writing, **no contract has ever been deployed to mainnet** —
`Contracts.ContractInfoOf` is empty across 2.7 million blocks.

---

## Connecting with py-substrate-interface

```python
SubstrateInterface(url=..., ss58_format=42, type_registry_preset="legacy")
```

The preset named in Portaldot's own documentation does not exist. `legacy` is
the one that decodes this runtime. Without it, `Proxy` types in particular fail
to decode and need manual aliases.

---

## Staking on V3: present, undocumented, unproven

V3 carries `Staking`, `NominationPools`, `DelegatedStaking`, `FastUnstake`,
`VoterList`, `Proxy` — 70 pallets against mainnet's 31.

But the official V3 developer guide covers **accounts, assets, NFTs and
Solidity**, and nothing else. Searching it for `stake`, `nominate`, `pool`,
`validator` or `delegate` returns two hits in 375 lines, both incidental.
The testnet itself runs one validator, zero nominators, zero pools.

So the pallets are there and nobody has shown they work on this build.

### `DelegatedStaking` cannot be called

The pallet has **no `#[pallet::call]` block at all**. Its functions —
`register_agent`, `delegate_to_agent`, `release_delegation` — take
`OriginFor<T>` and look exactly like dispatchables, but sit in a plain
`impl<T: Config> Pallet<T>`. The comment above them says so outright: the
pallet is not written with the intention of exposing calls.

It is a support pallet for `NominationPools`. The only way into delegated
staking is through pools.

*(Read from polkadot-sdk `master`, 7 October 2026. To be re-checked against
Portaldot's fork when their node returns.)*

### `NominationPools` role boundary

26 dispatchables. The permission functions are what make the pool worth using:

```rust
can_nominate(who)           is_root(who) || roles.nominator == who
can_update_roles(who)       is_root(who)
can_manage_commission(who)  is_root(who)
can_toggle_state(who)       (is_root || is_bouncer) && !is_destroying
can_kick(who)               state == Blocked && (is_root || is_bouncer)
```

An account holding only `nominator` can do exactly one thing: choose the
validators. Not commission, not roles, not membership, not funds. The bonded
account is keyless.

### `ProxyType::Staking` admits `set_payee`

```rust
ProxyType::Staking => matches!(c, Call::Staking(..))
```

That admits the whole of `pallet_staking`, including
`set_payee(Account(attacker))` — redirection of every future reward to an
arbitrary address. Anyone building "non-custodial" delegation on Portaldot with
an instant proxy is wrong about what they have built.

A delayed proxy closes it, because the pallet enforces the announcement itself:

```rust
ensure!(def.delay.is_zero(), Error::<T>::Unannounced);
```

### No precompile reaches staking

V3 exposes `AssetsPrecompiles`, `AssetsPrecompilesPermit` and
`VestingPrecompiles`. There is none for `Staking` or `NominationPools`, so a
Solidity contract on V3 cannot join a pool or read a member's points. A liquid
staking receipt on this chain has to be a native `Assets` asset, not an
ERC-20 — which is no loss, since the `Assets` precompile keeps it visible from
EVM and MetaMask anyway.

---

## History is kept, but only by their node

The staking pallet drops eras past `historyDepth` — 84 eras, 42 days:

```
ErasTotalStake(3780) at head                = 0
ErasTotalStake(3780) at block 2 646 514     = 4 165 199 880 336 017 606 088
```

Block 2 646 514 falls inside era 3780, 97 eras back. The pallet has forgotten
it; historical state has not, and `wss://mainnet.portaldot.io` answers
historical queries two million blocks deep.

So the honest statement is narrow: an ordinary query at the head returns
nothing past 84 eras, which is what every wallet and explorer does. The data
survives on one node under someone else's retention policy. Switch that node
to pruning and it is gone with nothing to ask.

---

## Two smaller things

**An account that does not exist produces blocks.** Roughly 1.3% of block
production is attributed to an address with an all-zero public key. Reported
separately.

**The guide ships a published mnemonic.** The official V3 sample code signs
with a seed phrase printed in the repository. If that account holds tPOTv3 it
is a de-facto faucet — and also drainable by anyone who opened the guide.
Nothing of value should live there.

---

## The V3 testnet is not reliable infrastructure

It runs on `feso-apps.xyz`, from a guide repository under a community account,
with one validator. Both RPC endpoints returned `502` continuously from
5 October 07:07 UTC through at least 7 October.

Plan around it: deploy when it answers, and keep the artefacts — code hash,
address, transaction hash — so a deployment can be shown even on a day the node
is down.
