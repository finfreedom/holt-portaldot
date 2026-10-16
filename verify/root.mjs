// Independent verification of a Holt attestation root.
//
// Written against docs/methodology.md and nothing else. One implementation
// proves the code agrees with itself; two prove the specification is complete.
//
//   node verify/root.mjs <path-to-holt.db> <era>

import { DatabaseSync } from 'node:sqlite';
import { blake2b256 } from './blake2b.mjs';

// No installed dependencies: someone checking our arithmetic should not have
// to trust a package tree first. node:sqlite ships with Node, and the hash
// is written out in blake2b.mjs.
const u8aConcat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};
const toHex = (u) => [...u].map((x) => x.toString(16).padStart(2, '0')).join('');

const DB = process.argv[2];
const ERA = Number(process.argv[3]);
if (!DB || !Number.isFinite(ERA)) {
  console.error('usage: node verify/root.mjs <holt.db> <era>');
  process.exit(2);
}

const b2 = (...parts) => blake2b256(u8aConcat(...parts));
const txt = (s) => new TextEncoder().encode(s);
const u8 = (n) => Uint8Array.from([n & 0xff]);
const u16 = (n) => Uint8Array.from([(n >> 8) & 0xff, n & 0xff]);

// Weights by permanent factor id, as hashed. Must match engine/config.py.
const CONFIG = {
  cap_bp: 2500,
  engine_version: 2,
  gate_commission_bp: 10000,
  max_targets: 16,
  weights: { 1: 3500, 2: 2000, 3: 2000, 4: 500, 6: 2000 },
};

// Factor 6 is a share of eras, so it already means the same thing in any
// company and is read as measured instead of against the set's range. Below
// this many archived eras it says more about how long we watched than about
// anyone's reliability, and switches off.
const ABSOLUTE = new Set([6]);
const MIN_ERAS_FOR_CONSISTENCY = 28;

// ── fixed-point log2, integer arithmetic only ────────────────────────────
// Deliberately re-derived from the written description rather than ported:
// a port would inherit the original's mistakes, which is the one thing a
// second implementation exists to catch.
const FRAC = 16n;
function log2fp(x) {
  x = BigInt(x);
  if (x <= 0n) return 0n;
  let n = BigInt(x.toString(2).length - 1);
  let result = n << FRAC;
  let y = (x << FRAC) >> n;
  const one = 1n << FRAC, two = one << 1n;
  for (let i = 0n; i < FRAC; i++) {
    y = (y * y) >> FRAC;
    if (y >= two) { y >>= 1n; result += 1n << (FRAC - 1n - i); }
  }
  return result;
}
const ratioBp = (a, b) => (b === 0n ? 0n : (a * 10000n) / b);

// ── raw factor values ────────────────────────────────────────────────────
const db = new DatabaseSync(DB, { readOnly: true });
const rows = db.prepare(
  `select ev.address, v.pubkey, ev.own, ev.total, ev.commission_bp,
          (select count(*) from offences o where o.address = ev.address) as offences,
          case when v.identity_json is null then 0 else 1 end as identity,
          (select count(distinct era) from era_validators x
            where x.address = ev.address) as seen
     from era_validators ev join validators v on v.address = ev.address
    where ev.era = ?`).all(ERA);
if (!rows.length) { console.error(`no data for era ${ERA}`); process.exit(1); }
const archived = db.prepare(
  'select count(distinct era) as n from era_validators').get().n;

const HIGHER_BETTER = { 1: false, 2: true, 3: false, 4: true, 6: true };
const vals = rows.map((r) => ({
  pk: new Uint8Array(r.pubkey),
  gated: r.commission_bp >= CONFIG.gate_commission_bp,
  raw: {
    1: BigInt(r.commission_bp),
    2: log2fp(1n + ratioBp(BigInt(r.own), BigInt(r.total))),
    3: log2fp(1n + BigInt(r.offences)),
    4: BigInt(r.identity),
    6: ratioBp(BigInt(r.seen), BigInt(archived || 1)),
  },
}));

// ── normalise, then score ────────────────────────────────────────────────
const ids = [1, 2, 3, 4, 6];
const range = {};
const isActive = {};
for (const id of ids) {
  const xs = vals.map((v) => v.raw[id]);
  range[id] = [xs.reduce((a, b) => (a < b ? a : b)), xs.reduce((a, b) => (a > b ? a : b))];
  isActive[id] = ABSOLUTE.has(id)
    ? archived >= MIN_ERAS_FOR_CONSISTENCY
    : range[id][0] !== range[id][1];
}
const activeTotal = ids
  .filter((id) => isActive[id])
  .reduce((acc, id) => acc + BigInt(CONFIG.weights[id]), 0n);

for (const v of vals) {
  let acc = 0n;
  v.factors = ids.map((id) => {
    const [lo, hi] = range[id];
    const active = isActive[id];
    let value = 0n;
    if (active) {
      if (ABSOLUTE.has(id)) {
        value = v.raw[id];
      } else {
        const t = ((v.raw[id] - lo) * 10000n) / (hi - lo);
        value = HIGHER_BETTER[id] ? t : 10000n - t;
      }
      acc += BigInt(CONFIG.weights[id]) * value;
    }
    return { id, value, weight: active ? BigInt(CONFIG.weights[id]) : 0n, active };
  });
  v.score = v.gated || activeTotal === 0n ? 0n : acc / activeTotal;
}

// ── leaves and root ──────────────────────────────────────────────────────
const canonical = (o) =>
  JSON.stringify(o, Object.keys(o).sort());   // keys sorted, no whitespace

vals.sort((a, b) => {
  for (let i = 0; i < 32; i++) if (a.pk[i] !== b.pk[i]) return a.pk[i] - b.pk[i];
  return 0;
});

const leaves = [b2(txt('holt.v1.config'), txt(canonicalConfig()))];
for (const v of vals) {
  const body = u8aConcat(...v.factors.map((f) =>
    u8aConcat(u8(f.id), u16(Number(f.value)), u16(Number(f.weight)), u8(f.active ? 1 : 0))));
  const fh = b2(txt('holt.v1.factors'), body);
  leaves.push(b2(txt('holt.v1.validator'), v.pk,
                 u16(Number(v.score)), u8(v.gated ? 1 : 0), fh));
}

function canonicalConfig() {
  // Sorted keys at every level, no whitespace — matches Python's
  // json.dumps(sort_keys=True, separators=(',', ':')).
  const w = CONFIG.weights;
  return `{"cap_bp":${CONFIG.cap_bp},"engine_version":${CONFIG.engine_version},`
    + `"gate_commission_bp":${CONFIG.gate_commission_bp},`
    + `"max_targets":${CONFIG.max_targets},`
    + `"weights":{${Object.keys(w).sort().map((k) => `"${k}":${w[k]}`).join(',')}}}`;
}

let level = leaves;
while (level.length > 1) {
  if (level.length % 2) level.push(level[level.length - 1]);
  const next = [];
  for (let i = 0; i < level.length; i += 2)
    next.push(b2(txt('holt.v1.node'), level[i], level[i + 1]));
  level = next;
}

console.log(`era ${ERA}: ${toHex(level[0])}`);
