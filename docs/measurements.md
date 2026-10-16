# Measurements

Every figure Holt publishes, with the date it was taken and the query that
took it. A number without a date stops being true quietly.

Source throughout: `wss://mainnet.portaldot.io`, finalised blocks only.

---

## Network, era 3876 — 7 October 2026

```
spec_name / spec_version   portaldot / 1002
pallets                    31
validators                 11          target 15
nominators                152
staked                     4.1%        of supply
existential deposit        1 POT
contracts.palletVersion    0
genesis   0x83b5212c69f85f3996f8696bb35bf913af51b176a5f53d0a74fd3a83dc0b8a54
```

### Cadence

```
ExpectedBlockTime        60 000 ms      one block per minute
EpochDuration           120 blocks      session, 2 hours
SessionsPerEra            6             era, 720 blocks, 12 hours
HistoryDepth             84 eras        42 days
BondingDuration          60 eras        30 days
```

---

## The eleven, era 3876

| Account | Stake | Blocks | Own | Delegators | Commission | Offences |
|---|---:|---:|---:|---:|---:|---:|
| `5CtnsMuscb2q…` | **87.39%** | 71 | 0.1% | 121 | 26.0% | **93** |
| `5DHWWSGrhRgv…` | 6.71% | 60 | 1.1% | 7 | 26.0% | 6 |
| `5FQzFfora2im…` | 2.43% | **83** | 2.6% | 2 | 30.0% | 11 |
| `5GUP3qMcdpAE…` | 2.31% | 66 | 3.1% | 1 | 25.0% | 66 |
| `5F4s9VGWseiY…` | 0.43% | 64 | 14.5% | 3 | 30.0% | 24 |
| `5ENZRaWjc4wr…` | 0.32% | 69 | 19.7% | 6 | 30.0% | 12 |
| `5FCM6payzb4z…` | 0.11% | 60 | 66.0% | 7 | 30.0% | 58 |
| `5DSHUMkUHoT7…` | 0.10% | 61 | 61.7% | 5 | *100.0%* | 2 |
| `5GNXYWQ7scTW…` | 0.07% | 64 | 100.0% | — | *100.0%* | 1 |
| `5CPtEfZXLyLA…` | 0.06% | 57 | 100.0% | — | *100.0%* | 2 |
| `5EhWJRiq4XLw…` | 0.06% | 65 | 100.0% | — | *100.0%* | 3 |
| **Eleven** | **100.00%** | **720** | | **152** | | **407** all-time |

Stake and commission from chain state; blocks counted from the BABE digest of
all 720 headers in the era.

## Effective decentralisation

`N_eff = 1 / Σf²` — the inverse Herfindahl index, applied to two different
quantities over the same accounts.

```
                     spread        N_eff
  blocks produced     1.46×        10.88
  stake held          1456×         1.30
```

Across all 97 archived eras, `N_eff` by stake has stayed between **1.2993 and
1.3011**. This is not a fluctuation; it is the resting state of the network.

## Allocation, era 3892

**What a nominator can actually choose.** On NPoS you submit a *set* of
targets, up to sixteen. You do not submit percentages. The election solver
spreads your stake across the set you named, and how it spreads is its
decision, not yours.

This matters because an earlier version of this page assigned each validator
a share — trimming the largest account to 9.9% of the portfolio instead of
excluding it. No such call exists. The only lever a nominator has is
membership: a validator is on the list or it is not.

So the plan is a list, and the largest account is **excluded rather than
trimmed**, because trimming is not on offer.

```
target            score   network share   why it is here
5ENZRaWjc4…        82.4           0.34%   clean offence record
5F4s9VGWse…        77.9           0.46%   sound across every factor
5FCM6payzb…        77.8           0.11%   high self-stake against total
5FQzFfora2…        76.8           2.61%   clean offence record
5GUP3qMcdp…        70.4           2.48%   lowest commission of the five

excluded, 100% commission     5DSHUMkUHoT7…  5GNXYWQ7scTW…
                              5CPtEfZXLyLA…  5EhWJRiq4XLw…
excluded, holds 93.66%        5CtnsMuscb2q…
```

**The threshold is relative, not a flat 25%.** A validator is excluded from
allocation when its share exceeds the cap *or* an even share of the set,
whichever is larger. A flat cap misfires on a small network: three validators
holding a third each are not concentrated, they are three validators, yet
every one of them clears 25% and the plan comes back empty.

**What the resulting figure means, exactly.** Five targets, assuming the
election spreads evenly across them, is `N_eff` **5.00** against the
network's **1.14**. The 5.00 equals the number of targets by construction —
it is not a separate discovery, and we are not claiming the solver will
split evenly. The comparison is the point: the same stake sits behind five
positions instead of effectively one.

**Scoring and allocation are separate, and here is where that bites.** The
largest account scores 57.0. That is a real score from its own conduct — 26%
commission, blocks produced on schedule — and it is not penalised for other
people's delegations. Allocation declines it anyway. A reader sees both: the
validator is sound, *and* it should not receive more.

**Why five and not ten.** Four validators charge 100% commission, which
returns a delegator nothing; one holds 93.66% of the network. Both numbers
improve the moment either condition changes, and neither is ours to change.

Both numbers improve if the network grows toward its target of fifteen
validators, and the second improves immediately if any of those four stops
charging 100%.

---

## Era 3873: the largest validator was absent

For exactly one era, the account holding 87.39% of stake with 121 delegators
dropped out of the set.

```
era 3872   11 validators   total stake 4 194 595 210
era 3873   10 validators   total stake   528 753 626    N_eff 2.81
era 3874   11 validators   total stake 4 194 607 915
```

Concentration halved for twelve hours and returned. Around era 3957 this
episode stops being answerable from current state.

---

## Offences are not slashes

`staking.unappliedSlashes` is empty; every recorded slash fraction is zero. All
407 records are unresponsiveness signals from `ImOnline`.

They are not evenly spread, and the largest validator carries the most:

```
5CtnsMuscb2qYf…   93     the 87.39% account
5GUP3qMcdpAE5t…   66
5FCM6payzb4zo3…   58
5EAR3dRonCoFvs…   52     not in the current set
5DCPHWcxnacBHY…   32     not in the current set
5EJJVkf69eFyTX…   30     not in the current set
```

Three of the top six are no longer validating — history the current set does
not show.

---

## Five accounts earning nothing

`5DSHUMkUHoT78n…` charges 100% commission and has five delegators. The whole
reward stays with the validator.

```
5FpQ27DxMj1EEaiGQsNkFWCFP2zHdpwJcPihS61YbSh7U3yA    1 000.00 POT
5GYqhodEAAtQjCcF8ZkoGxak3unCqcWQuBb4z5hHNATHoMBq    9 179.73 POT
5DFJBsTWFy3oYHJX2z4zHeC9eUxFKRL57xHXCirCsracKLvt    1 254.86 POT
5DkwMBnyxpr9u4xawpYV75zsD4G8oKcMUGqBruEatdHqHktA    1 442.59 POT
5Eo6N5xgH9SfM41SruRyyo2oAzhrH9udSZetTar1jm6ARBeN    3 207.94 POT
                                                   ─────────────
                                                   16 085.12 POT
```

0.04% of staked supply. The sum is not the point: nothing in the network tells
these five what is happening.

The other three 100%-commission validators have no delegators at all, which is
the arrangement working as intended.

---

## The archive

`holt-archive.db`, collecting since 30 September 2026.

```
eras                97        3780 – 3876
validator records    1 066
delegations         13 774
offences               407
block headers          720    era 3876, authors resolved
```

Twelve of those eras — 3780 through 3791 — are past `historyDepth` and no
longer answerable by an ordinary query at the chain head.

---

## A correction worth keeping

The project's original thesis was correlated-failure clusters: groups of
validators that would fail together, making a sixteen-validator portfolio
behave like one. We looked for them by payout address, stash/controller,
`identity.superOf` and coincident gaps in production.

**There are none on this network.**

An early run reported clusters. It had grouped by payout *variant* —
`Stash` versus `Staked` — rather than by payout *address*. The script was
wrong, the conclusion was reversed, and the concentration measurement above
replaced it.
