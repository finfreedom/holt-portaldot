// Independent verification of a Holt attestation root.
//
// Written against docs/methodology.md and nothing else. One implementation
// proves the code agrees with itself; two prove the specification is complete.
//
//   node verify/root.mjs <path-to-holt.db> <era>

import { DatabaseSync } from 'node:sqlite';
import { blake2AsU8a } from '@polkadot/util-crypto';
import { u8aConcat, u8aToHex } from '@polkadot/util';

const DB = process.argv[2];
const ERA = Number(process.argv[3]);
if (!DB || !Number.isFinite(ERA)) {
  console.error('usage: node verify/root.mjs <holt.db> <era>');
  process.exit(2);
}

const b2 = (...parts) => blake2AsU8a(u8aConcat(...parts), 256);
const txt = (s) => new TextEncoder().encode(s);
const u8 = (n) => Uint8Array.from([n & 0xff]);
const u16 = (n) => Uint8Array.from([(n >> 8) & 0xff, n & 0xff]);

// Weights by permanent factor id, as hashed. Must match engine/config.py.
const CONFIG = {
  cap_bp: 2500,
  engine_version: 1,
  gate_commission_bp: 10000,
  max_targets: 16,
  weights: { 1: 4000, 2: 2500, 3: 2500, 4: 1000 },
};

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
          case when v.identity_json is null then 0 else 1 end as identity
     from era_validators ev join validators v on v.address = ev.address
    where ev.era = ?`).all(ERA);
if (!rows.length) { console.error(`no data for era ${ERA}`); process.exit(1); }

const HIGHER_BETTER = { 1: false, 2: true, 3: false, 4: true };
const vals = rows.map((r) => ({
  pk: new Uint8Array(r.pubkey),
  gated: r.commission_bp >= CONFIG.gate_commission_bp,
  raw: {
    1: BigInt(r.commission_bp),
    2: log2fp(1n + ratioBp(BigInt(r.own), BigInt(r.total))),
    3: log2fp(1n + BigInt(r.offences)),
    4: BigInt(r.identity),
  },
}));

// ── normalise, then score ────────────────────────────────────────────────
const ids = [1, 2, 3, 4];
const range = {};
for (const id of ids) {
  const xs = vals.map((v) => v.raw[id]);
  range[id] = [xs.reduce((a, b) => (a < b ? a : b)), xs.reduce((a, b) => (a > b ? a : b))];
}
const activeTotal = ids
  .filter((id) => range[id][0] !== range[id][1])
  .reduce((acc, id) => acc + BigInt(CONFIG.weights[id]), 0n);

for (const v of vals) {
  let acc = 0n;
  v.factors = ids.map((id) => {
    const [lo, hi] = range[id];
    const active = lo !== hi;
    let value = 0n;
    if (active) {
      const t = ((v.raw[id] - lo) * 10000n) / (hi - lo);
      value = HIGHER_BETTER[id] ? t : 10000n - t;
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

console.log(`era ${ERA}: ${u8aToHex(level[0], -1, false)}`);
