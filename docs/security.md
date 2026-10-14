# Security

Holt takes no custody and no delegated authority, on any network. This document
says what that means precisely, what an attacker gains if our key leaks, and
what we rejected on the way.

---

## The position

| | mainnet | V3 testnet |
|---|---|---|
| what Holt does | reads | operates a nomination pool |
| authority held | **none** | `nominator` role only |
| can it sign for a user | no | no |
| what a stolen key reaches | nothing | the pool's target list |

On mainnet the engine computes a target set and publishes it. It never signs on
anyone's behalf. There is no proxy, no agent with authority over a stake, no
account whose compromise costs anyone anything. Nothing is defended because
nothing was taken.

On V3 the engine operates a nomination pool and holds only the `nominator`
role. `root` is dropped immediately after creation — a step enforced by test,
because while we hold `root` we hold everything `root` can do and the whole
argument collapses.

## The boundary is theirs, not ours

```rust
can_nominate(who)           is_root(who) || roles.nominator == who
can_update_roles(who)       is_root(who)
can_manage_commission(who)  is_root(who)
can_toggle_state(who)       (is_root || is_bouncer) && !is_destroying
can_kick(who)               state == Blocked && (is_root || is_bouncer)
```

A stolen agent key can submit a worse set of nominations and cost pool members
yield until the key is replaced. It cannot reach funds, commission, roles or
membership. The pool's bonded account is keyless; exit runs through `unbond`
and `withdraw_unbonded` by the member.

Lost yield is a different class of harm from theft, and the difference is
readable in five lines of someone else's code.

---

## What we rejected, and why

### A staking proxy

`ProxyType::Staking` on Portaldot's runtime admits the whole of
`pallet_staking`:

```rust
ProxyType::Staking => matches!(c, Call::Staking(..))
```

That includes `set_payee(Account(attacker))` — redirection of every future
reward to an arbitrary address. The principal is safe; the income stream is
not. Anyone shipping "non-custodial" delegation on Portaldot with an instant
proxy has not read this.

A **delayed** proxy closes it, and the pallet enforces the delay itself:

```rust
ensure!(def.delay.is_zero(), Error::<T>::Unannounced);
```

The agent must announce, the delay elapses in public, and the owner can reject.
We designed that, built the flow end to end, and then removed it — because its
safety rests on the owner watching announcements, and a mechanism that needs
vigilance is weaker than one that needs nothing.

### `DelegatedStaking`

Present on V3 and uncallable: the pallet exposes no dispatchables at all.
See `findings.md`.

---

## Standing rules

- **Signing key only from `HOLT_SIGNER_URI`.** Without it the engine runs
  `--dry-run` and does not attempt to sign.
- **One module touches keys.** Nothing else imports it.
- **The key never appears** in logs, error text, tracebacks or serialisation.
  Enforced by test.
- **No key in the repository**, in any file, at any point in history. That
  includes third-party published mnemonics copied from other projects' guides.
- **Attestation `commit` is owner-only**, with a test that a non-owner is
  rejected.
- **Only finalised blocks are indexed.**
- **Instant proxies are not supported at all**, in any code path.
- **Offences are never called slashes.**

---

## Open

`NominationPools` has not been exercised on Portaldot's V3 build. Their
developer guide does not cover staking, the testnet runs one validator and zero
pools, and the RPC has been down since 5 October. The first action there is a
single transaction that creates a pool and nominates — before any interface is
built on top of it. If the pallet does not work, that costs one transaction
instead of a milestone.
