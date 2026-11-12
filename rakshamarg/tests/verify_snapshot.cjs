// node tests/verify_snapshot.cjs <overpass-snapshot.json> : prove the real-roads presets work on a saved OSM extract.
const fs = require("fs"), path = require("path"), RM = require(path.join(__dirname, "../web/engine.js"));
globalThis.window = globalThis; require("vm").runInThisContext(fs.readFileSync(path.join(__dirname, "../web/data_sim.js"), "utf8"));
const snap = JSON.parse(fs.readFileSync(process.argv[2], "utf8")), g = RM.buildOsmGraph(snap), D = globalThis.RM_SIM;
const core = new Set(); g.edges.filter((e) => e.cls === "NH").forEach((e) => [e.u, e.v].forEach((id) => { const n = g.nodeById.get(id); if (n.comp === g.mainComp) core.add(n); }));
const ends = [...core].sort((a, b) => a.lon - b.lon);
const presets = { "NH-19 west → east": ends.length > 1 ? [ends[0], ends[ends.length - 1]] : null,
                  "Near Prayagraj Jn → Naini": [RM.nearestNode(g, 25.4454, 81.8264), RM.nearestNode(g, 25.3900, 81.8800)] };
const pol = { maxExtra: 12, minCut: 15, pReq: 0.9 }, zone = { name: "Sangam / Mela area", lat: 25.4240, lon: 81.8850, radiusKm: 3, start: 0, end: 24, active: true };
const rep = { osm_base: g.stats.osm_base, stats: g.stats, presets: {} }; let ok = !!g.stats.osm_base;
for (const [name, p] of Object.entries(presets)) {
  if (!p || !p[0] || !p[1]) { rep.presets[name] = { reachable: false }; ok = false; continue; }
  const res = { reachable: !!RM.dijkstra(g, p[0].id, p[1].id, (e) => g.edges[e].time), snap_m: p.map((n) => Math.round((n.snapKm || 0) * 1000)) };
  for (const [tb, w] of [["day", "clear"], ["night", "fog"]]) {
    const cc = RM.coldContext(g, D.cold, tb, w), R = RM.decideOn(g, p[0].id, p[1].id, cc.rate, cc.mult, 1, tb, pol, new Set());
    res[`${tb}/${w}`] = { decision: R.decision, cause: R.cause || null, km: R.chosen ? +R.chosen.km.toFixed(1) : null, min: R.chosen ? +R.chosen.time.toFixed(1) : null, consistent: R.consistent };
    if (!R.consistent || R.decision === "no_legal_route") ok = false;
  }
  const cc = RM.coldContext(g, D.cold, "day", "clear"), base = RM.decideOn(g, p[0].id, p[1].id, cc.rate, cc.mult, 1, "day", pol, new Set());
  const z = RM.decideOn(g, p[0].id, p[1].id, cc.rate, cc.mult, 1, "day", pol, RM.zoneBans(g, [zone], 12));
  res.with_mela_zone = { decision: z.decision, cause: z.cause || null, route_changed: !!(base.chosen && z.chosen && base.chosen.eids.join() !== z.chosen.eids.join()), blocked_segments: RM.zoneBans(g, [zone], 12).size };
  rep.presets[name] = res; ok = ok && res.reachable;
}
rep.ok = ok; console.log(JSON.stringify(rep, null, 1)); process.exit(ok ? 0 : 1);
