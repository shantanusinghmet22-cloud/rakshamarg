// node tests/test_engine.cjs : browser-engine parity with the Python reference + real-road adapter tests
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");
const ROOT = path.join(__dirname, "..");
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(path.join(ROOT, "web/data_sim.js"), "utf8"));
const RM = require(path.join(ROOT, "web/engine.js"));
const D = globalThis.RM_SIM, ref = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/parity_reference.json"), "utf8"));
assert.strictEqual(ref.source_sha256_12, D.meta.source_sha256_12, "data and reference from different releases");
const g = RM.loadSim(D);
const pol = { maxExtra: 12, minCut: 15, pReq: 0.9 };
let candOK = 0, pointMax = 0, decAgree = 0, nearThreshold = 0, other = [], inconsistent = 0;
const t0 = Date.now();
for (const tr of ref.trips) {
  const R = RM.decide(g, tr.o, tr.d, tr.ctx, pol);
  if (!R.consistent) inconsistent++;
  const jsC = R.opts.map((o) => o.eids);
  if (JSON.stringify(jsC) === JSON.stringify(tr.candidates)) candOK++;
  R.opts.forEach((o, i) => { if (tr.point[i] !== undefined) pointMax = Math.max(pointMax, Math.abs(o.point - tr.point[i]) / Math.max(tr.point[i], 1e-12)); });
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  if (R.decision === tr.decision && same(R.chosen ? R.chosen.eids : null, tr.chosen) && same(R.fastest ? R.fastest.eids : null, tr.fastest)
      && same(R.considered ? R.considered.eids : null, tr.considered)) decAgree++;
  else {
    const p = tr.p !== null ? tr.p : R.p;
    if ((p !== null && Math.abs(p - 0.9) < 0.06) || (R.p !== null && Math.abs(R.p - 0.9) < 0.06)) nearThreshold++;
    else other.push({ o: tr.o, d: tr.d, ctx: tr.ctx, py: tr.decision, js: R.decision, pyP: tr.p, jsP: R.p });
  }
}
const ms = (Date.now() - t0) / ref.trips.length;
const res = { trips: ref.trips.length, candidate_sets_identical: candOK, max_rel_point_risk_diff: pointMax, decisions_agree: decAgree,
  disagreements_near_threshold: nearThreshold, other_disagreements: other.length, inconsistent, ms_per_decision: +ms.toFixed(1) };
console.log(JSON.stringify(res, null, 1));
fs.mkdirSync(path.join(ROOT, "outputs/test_results"), { recursive: true });   // test artefacts live outside the release manifest
fs.writeFileSync(path.join(ROOT, "outputs/test_results/parity_result.json"), JSON.stringify(Object.assign({ source_sha256_12: ref.source_sha256_12 }, res)));
if (other.length) console.log("OTHER:", JSON.stringify(other.slice(0, 5)));
assert.strictEqual(inconsistent, 0); assert.strictEqual(candOK, ref.trips.length, "candidate sets must be identical (exact parity gate)");
assert.ok(pointMax < 1e-4, "point risks diverge");
assert.strictEqual(decAgree, ref.trips.length, "decisions and fastest/considered/chosen routes must match the archived Python reference on every trip");

// ---------------- real-road adapters on an Overpass-shaped fixture (synthetic geometry near Prayagraj)
const els = [], N = (id, lat, lon) => els.push({ type: "node", id, lat, lon });
for (let i = 0; i <= 10; i++) { N(100 + i, 25.40, 81.70 + 0.03 * i); N(200 + i, 25.45 + 0.004 * Math.sin(i), 81.70 + 0.03 * i); }
N(301, 25.425, 81.70); N(302, 25.425, 82.00);
els.push({ type: "way", id: 1, nodes: [...Array(11).keys()].map((i) => 100 + i), tags: { highway: "trunk", ref: "NH19", lit: "no" } });
els.push({ type: "way", id: 2, nodes: [...Array(11).keys()].map((i) => 200 + i), tags: { highway: "secondary", maxspeed: "40" } });
els.push({ type: "way", id: 3, nodes: [100, 301, 200], tags: { highway: "tertiary" } });
els.push({ type: "way", id: 4, nodes: [110, 302, 210], tags: { highway: "tertiary" } });
els.push({ type: "way", id: 5, nodes: [105, 205], tags: { highway: "residential" } });   // must be ignored
const og = RM.buildOsmGraph({ elements: els });
assert.ok(og.edges.length >= 4 && og.edges.every((e) => e.len > 0 && isFinite(e.curv) && e.time > 0));
assert.ok(og.edges.some((e) => e.cls === "NH") && !og.edges.some((e) => e.highway === "residential"));
const tb = "night", cc = RM.coldContext(og, D.cold, tb, "fog");
assert.ok(cc.rate.every((r) => r > 0 && isFinite(r)));
const a = RM.nearestNode(og, 25.40, 81.70), b = RM.nearestNode(og, 25.40, 82.00);
const R1 = RM.decideOn(og, a.id, b.id, cc.rate, cc.mult, RM.median(cc.rate) * 30 * 1000, tb, pol, new Set());
assert.ok(R1.opts.length >= 2 && RM.isConsistent(R1));
const allBanned = RM.zoneBans(og, [{ lat: 25.425, lon: 81.85, radiusKm: 30, start: 0, end: 24, active: true }], 3);
const R2 = RM.decideOn(og, a.id, b.id, cc.rate, cc.mult, 1, tb, pol, allBanned);
assert.strictEqual(R2.decision, "no_legal_route");
const om = { hourly: { time: ["2026-12-20T02:00", "2026-12-20T03:00", "2026-12-20T15:00"], weather_code: [45, 3, 61], visibility: [400, 8000, 6000], precipitation: [0, 0, 1.2] } };
assert.strictEqual(RM.weatherFromOpenMeteo(om, "2026-12-20T02:00").weather, "fog");
assert.strictEqual(RM.weatherFromOpenMeteo(om, "2026-12-20T03:00").weather, "clear");
assert.strictEqual(RM.weatherFromOpenMeteo(om, "2026-12-20T15:00").weather, "rain");
assert.ok(Math.abs(RM.poissonSf(3, 1.0) - 0.0803013970713942) < 1e-12);
console.log("REAL-ROAD ADAPTER TESTS PASSED (osm edges:", og.edges.length, "| fixture decision:", R1.decision, ")");
console.log("ENGINE PARITY TESTS PASSED");
