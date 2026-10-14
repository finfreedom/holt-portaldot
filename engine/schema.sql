-- Holt schema. One SQLite file, no ORM.
--
-- Principles:
--  * only finalised state is written — a reorg must never rewrite history;
--  * we keep more than the chain does: historyDepth is 84 eras, we have no limit;
--  * the all-zero account 5C4hrfjw9DjXZ… never enters, at any door;
--  * u128 amounts are stored as TEXT. SQLite integers are 64-bit and a total
--    stake of 4.19e21 does not fit; REAL would round it. All arithmetic on
--    these values is integer arithmetic in Python.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Housekeeping: what this database is and how far it has been collected.
CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Every validator ever seen. Departed ones are not deleted: the offence
-- history is wider than the current set, and that history is the point.
CREATE TABLE IF NOT EXISTS validators (
    address        TEXT PRIMARY KEY,   -- SS58, prefix 42
    pubkey         BLOB NOT NULL,      -- 32 bytes, the canonical sort order
    first_seen_era INTEGER NOT NULL,
    last_seen_era  INTEGER NOT NULL,
    identity_json  TEXT,               -- NULL when identity is not set
    super_of       TEXT,               -- parent identity, when there is one
    payee_kind     TEXT,               -- Staked | Stash | Controller | Account | None
    payee_account  TEXT,               -- set only when payee_kind = Account
    controller     TEXT
);
CREATE INDEX IF NOT EXISTS ix_validators_pubkey ON validators(pubkey);

-- One row per era: the network as a whole.
CREATE TABLE IF NOT EXISTS eras (
    era               INTEGER PRIMARY KEY,
    started_at_block  INTEGER,
    total_stake       TEXT NOT NULL,   -- u128 as text
    validator_reward  TEXT,            -- NULL until the era is paid out
    total_points      INTEGER NOT NULL,
    validator_count   INTEGER NOT NULL,
    collected_at      TEXT NOT NULL    -- ISO-8601, when we wrote it
);

-- A validator within an era: exposure, commission, points.
CREATE TABLE IF NOT EXISTS era_validators (
    era              INTEGER NOT NULL,
    address          TEXT NOT NULL,
    own              TEXT NOT NULL,    -- u128
    total            TEXT NOT NULL,    -- u128
    nominator_count  INTEGER NOT NULL,
    commission_bp    INTEGER NOT NULL, -- basis points, 0..10000
    reward_points    INTEGER NOT NULL,
    is_active        INTEGER NOT NULL, -- 0/1: present in session.validators
    PRIMARY KEY (era, address),
    FOREIGN KEY (address) REFERENCES validators(address)
);
CREATE INDEX IF NOT EXISTS ix_ev_address ON era_validators(address);

-- Who backed whom. Needed for N_eff of an individual nominator's portfolio.
CREATE TABLE IF NOT EXISTS era_nominations (
    era        INTEGER NOT NULL,
    nominator  TEXT NOT NULL,
    validator  TEXT NOT NULL,
    amount     TEXT NOT NULL,          -- u128, this nominator's part of the exposure
    PRIMARY KEY (era, nominator, validator)
);
CREATE INDEX IF NOT EXISTS ix_en_nominator ON era_nominations(nominator);
CREATE INDEX IF NOT EXISTS ix_en_validator ON era_nominations(era, validator);

-- Offences. These are NOT slashes: unappliedSlashes is empty and every
-- recorded slash fraction is zero. They are unresponsiveness signals from
-- ImOnline. Calling them slashes anywhere user-facing would be a lie.
CREATE TABLE IF NOT EXISTS offences (
    report_id     TEXT PRIMARY KEY,    -- hash of the record
    era           INTEGER,             -- NULL when the era could not be resolved
    address       TEXT NOT NULL,
    kind          TEXT,
    slash_fraction_bp INTEGER NOT NULL DEFAULT 0,
    seen_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_off_address ON offences(address);

-- Scoring results. Everything needed to recompute the merkle root
-- independently, per docs/methodology.md.
CREATE TABLE IF NOT EXISTS scores (
    era             INTEGER NOT NULL,
    address         TEXT NOT NULL,
    score_bp        INTEGER NOT NULL,  -- 0..10000
    gated           INTEGER NOT NULL,  -- 0/1
    gate_reason     TEXT,
    factors_json    TEXT NOT NULL,     -- canonical, ordered by factor_id
    engine_version  INTEGER NOT NULL,
    config_hash     TEXT NOT NULL,     -- hex blake2-256
    PRIMARY KEY (era, address, engine_version, config_hash)
);

-- What we committed on chain, and when.
CREATE TABLE IF NOT EXISTS attestations (
    era             INTEGER NOT NULL,
    root            TEXT NOT NULL,     -- hex blake2-256
    engine_version  INTEGER NOT NULL,
    config_hash     TEXT NOT NULL,
    tx_hash         TEXT,
    block           INTEGER,
    PRIMARY KEY (era, engine_version, config_hash)
);

-- A log of allocation decisions. Shown to the user and used for post-hoc
-- review: intent, outcome, and the reason either way.
CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    era          INTEGER NOT NULL,
    account      TEXT NOT NULL,
    current_json TEXT NOT NULL,        -- the current target set
    target_json  TEXT NOT NULL,        -- the proposed target set
    applied      INTEGER NOT NULL,     -- 0/1
    reason       TEXT NOT NULL,        -- why it was applied, or why it was not
    call_hash    TEXT,                 -- hash of the announced call
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dec_account ON decisions(account, era);
