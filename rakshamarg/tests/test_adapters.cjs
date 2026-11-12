// node tests/test_adapters.cjs : real-road adapter semantics (the judge review's counterexamples, F02-F04, F11, F15)
const assert = require("assert"), path = require("path"), RM = require(path.join(__dirname, "../web/engine.js"));
const pol = { maxExtra: 12, minCut: 0, pReq: 0.5 };
const N = (id, lat, lon) => ({ type: "node", id, lat, lon }), Wy = (id, nodes, tags) => ({ type: "way", id, nodes, tags: Object.assign({ highway: "secondary" }, tags) });
const route = (g, a, b) => RM.dijkstra(g, String(a), String(b), (e) => g.edges[e].time);
const res = {};
// 1) oneway=-1 travels only against node order
let g = RM.buildOsmGraph({ elements: [N(1, 25.40, 81.70), N(2, 25.40, 81.72), Wy(1, [1, 2], { oneway: "-1" })] });
assert.ok(!route(g, 1, 2) && route(g, 2, 1)); res.reverse_oneway = "ok";
// 2) roundabout without oneway tag is one-way in node order
g = RM.buildOsmGraph({ elements: [N(1, 25.40, 81.70), N(2, 25.40, 81.71), Wy(1, [1, 2], { junction: "roundabout" })] });
assert.ok(route(g, 1, 2) && !route(g, 2, 1)); res.roundabout = "ok";
// 3) access restrictions for heavy vehicles; unsupported constraints are flagged, not silently trusted
const acc = (tags) => RM.buildOsmGraph({ elements: [N(1, 25.40, 81.70), N(2, 25.40, 81.72), Wy(1, [1, 2], tags)] });
assert.strictEqual(acc({ hgv: "no" }).edges.length, 0); assert.strictEqual(acc({ access: "no" }).edges.length, 0);
assert.strictEqual(acc({ motor_vehicle: "no" }).edges.length, 0); assert.strictEqual(acc({ access: "no", hgv: "designated" }).edges.length, 1);
assert.deepStrictEqual(acc({ maxweight: "10" }).edges[0].warn, ["maxweight=10"]); res.access = "ok";
// 4) a road crossing a restriction circle is blocked even with no vertex inside
g = RM.buildOsmGraph({ elements: [N(1, 25.40, 81.70), N(2, 25.40, 81.74), Wy(1, [1, 2], {})] });
const z = { name: "test", lat: 25.40, lon: 81.72, radiusKm: 0.5, start: 0, end: 24, active: true };
assert.strictEqual(RM.zoneBans(g, [z], 12).size, 1);
assert.strictEqual(RM.zoneBans(g, [Object.assign({}, z, { lat: 25.42 })], 12).size, 0);            // 2.2 km away: not blocked
assert.strictEqual(RM.zoneBans(g, [Object.assign({}, z, { start: 22, end: 6 })], 23).size, 1);      // overnight window
assert.strictEqual(RM.zoneBans(g, [Object.assign({}, z, { start: 22, end: 6 })], 12).size, 0); res.zone_crossing = "ok";
// 5) parallel roads between the same junctions both stay in the candidate set
g = RM.buildOsmGraph({ elements: [N(1, 25.40, 81.70), N(2, 25.40, 81.75), N(3, 25.401, 81.725),
  Wy(1, [1, 2], { highway: "primary" }), Wy(2, [1, 3, 2], { highway: "secondary" })] });
const rate = g.edges.map((e) => (e.highway === "primary" ? 5e-5 : 1e-6));
const cands = RM.candidateRoutes(g, "1", "2", rate, new Set());
assert.strictEqual(cands.length, 2, "parallel low-risk road must be offered"); res.parallel_edges = "ok";
// 6) one-way dead ends: endpoints snap to the strongly connected core, so presets are routable
g = RM.buildOsmGraph({ elements: [N(1, 25.40, 81.70), N(2, 25.40, 81.72), N(3, 25.40, 81.74), N(4, 25.40, 81.76),
  Wy(1, [1, 2, 3], {}), Wy(2, [3, 4], { oneway: "yes" })] });
assert.strictEqual(RM.nearestNode(g, 25.40, 81.76).id, "3", "dead-end node 4 is outside the core");
assert.strictEqual(RM.nearestNode(g, 25.40, 81.76, false).id, "4"); res.scc_snapping = "ok";
// 7) no-route causes are distinguished
g = RM.buildOsmGraph({ elements: [N(1, 25.40, 81.70), N(2, 25.40, 81.74), N(3, 25.50, 81.90), N(4, 25.50, 81.92), Wy(1, [1, 2], {}), Wy(2, [3, 4], {})] });
const cc = { rate: g.edges.map(() => 1e-5), mult: null };
assert.strictEqual(RM.decideOn(g, "1", "3", cc.rate, null, 1, "day", pol, new Set()).cause, "network_unreachable");
assert.strictEqual(RM.decideOn(g, "1", "2", cc.rate, null, 1, "day", pol, RM.zoneBans(g, [z], 12)).cause, "blocked_by_restrictions"); res.no_route_causes = "ok";
// 8) restriction that opens while the truck is on the road
g = RM.buildOsmGraph({ elements: [N(1, 25.40, 81.60), N(2, 25.40, 81.72), Wy(1, [1, 2], { highway: "tertiary" })] });
const p = RM.dijkstra(g, "1", "2", (e) => g.edges[e].time);
const late = Object.assign({}, z, { lat: 25.40, lon: 81.715, radiusKm: 0.3, start: 23, end: 24 });
assert.strictEqual(RM.zoneBans(g, [late], 22.8).size, 0, "inactive at departure");
assert.ok(RM.enRouteConflicts(g, { eids: p.eids }, [late], 22.8).length >= 1, "but active while the truck is on that road");
assert.strictEqual(RM.enRouteConflicts(g, { eids: p.eids }, [late], 20.0).length, 0, "finished long before the window opens"); res.en_route = "ok";
// 9) weather outside the forecast window is unknown, never silently 'clear'
assert.strictEqual(RM.weatherFromOpenMeteo({ hourly: { time: ["2026-11-10T01:00"], weather_code: [0], visibility: [9000], precipitation: [0] } }, "2026-12-30T01:00"), null);
res.weather_unknown = "ok";
console.log(JSON.stringify(res)); console.log("ADAPTER SEMANTICS TESTS PASSED");
