/* RakshaMarg decision engine (browser + Node). A line-by-line port of rakshamarg/pipeline.py decision logic:
 * candidate_routes (networkx Yen k-shortest + risk-penalised Dijkstra), score_route, multiplier draws,
 * pareto, recommend (switch / keep / defer / no_legal_route), explain_segments, risk_index, post-trip check.
 * Plus adapters for real roads: OpenStreetMap (Overpass JSON) -> road graph, Open-Meteo -> context.
 * Parity with the Python reference is tested in tests/test_engine.mjs. */
(function (root) {
  "use strict";
  const RM = {};

  // ------------------------------------------------------------------ numerics
  RM.mulberry32 = function (a) {
    return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  function normals(rng, n) {
    const out = new Float64Array(n);
    for (let i = 0; i < n; i += 2) {
      let u = rng(); if (u < 1e-12) u = 1e-12; const v = rng(), r = Math.sqrt(-2 * Math.log(u));
      out[i] = r * Math.cos(2 * Math.PI * v); if (i + 1 < n) out[i + 1] = r * Math.sin(2 * Math.PI * v);
    }
    return out;
  }
  RM.quantile = function (arr, q) {            // numpy default (linear interpolation)
    const a = Float64Array.from(arr).sort(), h = (a.length - 1) * q, lo = Math.floor(h);
    return lo + 1 < a.length ? a[lo] + (h - lo) * (a[lo + 1] - a[lo]) : a[lo];
  };
  RM.median = function (arr) { return RM.quantile(arr, 0.5); };
  RM.poissonSf = function (k, lam) {           // P(X >= k)
    if (k <= 0) return 1; let p = Math.exp(-lam), c = p;
    for (let i = 1; i < k; i++) { p *= lam / i; c += p; }
    return Math.max(0, 1 - c);
  };
  RM.riskIndex = (v, ref) => 100 * (1 - Math.exp(-Math.LN2 * v / ref));
  RM.timeBucket = (h) => (h >= 6 && h < 18 ? "day" : h >= 18 && h < 22 ? "evening" : "night");

  // ------------------------------------------------------------------ graph
  RM.makeGraph = function (nodes, edges) {     // edges: {id,u,v,len,time,dir?}  dir: 0 both ways, 1 u->v only, -1 v->u only
    const adj = new Map(); nodes.forEach((n) => adj.set(n.id, []));
    edges.forEach((e) => { const d = e.dir === undefined ? (e.oneway ? 1 : 0) : e.dir;
      if (d >= 0) adj.get(e.u).push({ to: e.v, eid: e.id }); if (d <= 0) adj.get(e.v).push({ to: e.u, eid: e.id }); });
    return { nodes, edges, adj, nodeById: new Map(nodes.map((n) => [n.id, n])) };
  };
  class Heap {
    constructor() { this.a = []; }
    push(x) { const a = this.a; a.push(x); let i = a.length - 1; while (i > 0) { const p = (i - 1) >> 1; if (cmp(a[i], a[p]) >= 0) break; [a[i], a[p]] = [a[p], a[i]]; i = p; } }
    pop() { const a = this.a, top = a[0], last = a.pop(); if (a.length) { a[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let m = i;
      if (l < a.length && cmp(a[l], a[m]) < 0) m = l; if (r < a.length && cmp(a[r], a[m]) < 0) m = r; if (m === i) break; [a[i], a[m]] = [a[m], a[i]]; i = m; } } return top; }
    get size() { return this.a.length; }
  }
  const cmp = (x, y) => (x[0] - y[0]) || (x[1] - y[1]);
  RM.dijkstra = function (g, s, t, wfn, ignoreNodes, ignoreEdges, banned) {
    const dist = new Map([[s, 0]]), prev = new Map(), done = new Set(), h = new Heap(); let c = 0;
    h.push([0, c++, s]);
    while (h.size) {
      const [d, , u] = h.pop(); if (done.has(u)) continue; done.add(u);
      if (u === t) break;
      for (const { to, eid } of g.adj.get(u)) {
        if ((ignoreNodes && ignoreNodes.has(to)) || (ignoreEdges && ignoreEdges.has(eid)) || (banned && banned.has(eid))) continue;
        const nd = d + wfn(eid);
        if (!dist.has(to) || nd < dist.get(to)) { dist.set(to, nd); prev.set(to, [u, eid]); h.push([nd, c++, to]); }
      }
    }
    if (!done.has(t)) return null;
    const path = [t], eids = []; let x = t;
    while (x !== s) { const [p, e] = prev.get(x); eids.push(e); path.push(p); x = p; }
    return { cost: dist.get(t), path: path.reverse(), eids: eids.reverse() };
  };
  RM.kShortest = function (g, s, t, K, wfn, banned) {   // networkx.shortest_simple_paths semantics
    const A = [], B = new Heap(), inB = new Set(); let c = 0;
    const push = (cost, p) => { const k = p.eids.join("|"); if (!inB.has(k)) { inB.add(k); B.push([cost, c++, p]); } };
    const first = RM.dijkstra(g, s, t, wfn, null, null, banned); if (!first) return [];
    push(first.cost, first);
    while (A.length < K) {
      if (A.length) {
        const prev = A[A.length - 1], ignN = new Set(), ignE = new Set();
        for (let i = 1; i < prev.path.length; i++) {
          const rootP = prev.path.slice(0, i), rootE = prev.eids.slice(0, i - 1);
          let rootCost = 0; rootE.forEach((e) => (rootCost += wfn(e)));
          for (const p of A) if (p.eids.length > i - 1 && p.path[0] === rootP[0] && rootE.every((e, j) => p.eids[j] === e)) ignE.add(p.eids[i - 1]);
          const spur = RM.dijkstra(g, rootP[i - 1], t, wfn, ignN, ignE, banned);
          if (spur) push(rootCost + spur.cost, { path: rootP.slice(0, -1).concat(spur.path), eids: rootE.concat(spur.eids) });
          ignN.add(rootP[i - 1]);
        }
      }
      if (!B.size) break;
      const [, , p] = B.pop(); inB.delete(p.eids.join("|")); A.push(p);
    }
    return A;
  };

  // ------------------------------------------------------------------ candidate routes / scoring / policy
  RM.candidateRoutes = function (g, o, d, rate, banned, K = 4, alphas = [0.5, 1, 2, 4, 8]) {
    if (!RM.dijkstra(g, o, d, (e) => g.edges[e].time, null, null, banned)) return [];
    const out = [], seen = new Set(), add = (p) => { const k = p.eids.join("|"); if (!seen.has(k)) { seen.add(k); out.push(p); } };
    RM.kShortest(g, o, d, K, (e) => g.edges[e].time, banned).forEach(add);
    const med = RM.median(rate);
    for (const a of alphas) add(RM.dijkstra(g, o, d, (e) => g.edges[e].time + a * rate[e] / med * g.edges[e].len, null, null, banned));
    return out;
  };
  RM.multiplierDraws = function (nE, sd, cls, nCls, sdCtx, S, seed) {
    const rng = RM.mulberry32(seed), zc = normals(rng, S * nCls), zi = normals(rng, S * nE), zx = normals(rng, S);
    const m = new Float64Array(S * nE), h = Math.SQRT1_2;
    for (let s = 0; s < S; s++) for (let e = 0; e < nE; e++) {
      const v = sd[e] * (h * zc[s * nCls + cls[e]] + h * zi[s * nE + e]) + sdCtx * zx[s] - 0.5 * (sd[e] * sd[e] + sdCtx * sdCtx);
      m[s * nE + e] = Math.exp(v);
    }
    return { m, S, nE };
  };
  RM.scoreRoute = function (g, p, rate, mult, qDecision = 0.8) {
    const seg = p.eids.map((e) => rate[e] * g.edges[e].len * 1000);
    const total = seg.reduce((a, b) => a + b, 0);
    const out = { eids: p.eids, path: p.path, seg, point: total, time: p.eids.reduce((a, e) => a + g.edges[e].time, 0),
                  km: p.eids.reduce((a, e) => a + g.edges[e].len, 0), draws: null };
    if (mult) {
      const d = new Float64Array(mult.S);
      for (let s = 0; s < mult.S; s++) { let acc = 0; const off = s * mult.nE; p.eids.forEach((e, j) => (acc += mult.m[off + e] * seg[j])); d[s] = acc; }
      out.draws = d; out.lo = RM.quantile(d, 0.05); out.hi = RM.quantile(d, 0.95); out.q = RM.quantile(d, qDecision);
      const w = (out.hi - out.lo) / Math.max(total, 1e-12);
      out.confidence = w < 0.6 ? "High" : w < 1.2 ? "Medium" : "Low";
    }
    return out;
  };
  const drisk = (o) => (o.draws ? o.q : o.point);
  RM.pareto = function (opts) {
    return opts.map((a, i) => !opts.some((b, j) => j !== i && b.time <= a.time && drisk(b) <= drisk(a) && (b.time < a.time || drisk(b) < drisk(a))));
  };
  RM.recommend = function (opts, maxExtra = 12, minCut = 15, pReq = 0.9) {
    if (!opts.length) return { decision: "no_legal_route", fastest: null, considered: null, chosen: null, p: null, nQual: 0 };
    let fastest = opts[0]; opts.forEach((o) => { if (o.time < fastest.time) fastest = o; });
    const par = RM.pareto(opts), qual = [], same = (a, b) => a.eids.length === b.eids.length && a.eids.every((e, i) => e === b.eids[i]);
    opts.forEach((o, i) => {
      if (!par[i] || o === fastest || same(o, fastest)) return;
      const dt = (o.time - fastest.time) / fastest.time * 100, dr = (drisk(fastest) - drisk(o)) / drisk(fastest) * 100;
      if (dt <= maxExtra && dr >= minCut) qual.push([dr / Math.max(dt, 0.5), o]);
    });
    qual.sort((a, b) => b[0] - a[0]);
    if (!qual.length) return { decision: "keep", fastest, considered: null, chosen: fastest, p: null, nQual: 0 };
    if (!fastest.draws) return { decision: "switch", fastest, considered: qual[0][1], chosen: qual[0][1], p: null, nQual: qual.length };
    const ps = qual.map(([, o]) => { let n = 0; for (let s = 0; s < o.draws.length; s++) if (o.draws[s] < fastest.draws[s]) n++; return [n / o.draws.length, o]; });
    const S = fastest.draws.length, bl = (p) => Math.abs(p - pReq) <= 1.96 * Math.sqrt(Math.max(p * (1 - p), 1e-4) / S);
    for (const [p, o] of ps) if (p >= pReq) return { decision: "switch", fastest, considered: o, chosen: o, p, nQual: qual.length, borderline: bl(p) };
    const best = ps.reduce((a, b) => (b[0] > a[0] ? b : a));
    return { decision: "defer", fastest, considered: best[1], chosen: fastest, p: best[0], nQual: qual.length, borderline: bl(best[0]) };
  };
  RM.isConsistent = function (R) {
    if (R.decision === "no_legal_route") return R.chosen === null;
    const same = R.chosen.eids.join() === R.fastest.eids.join();
    return R.decision === "switch" ? !same : same;
  };
  RM.explain = function (g, opt, tb, hotspots, top = 3) {
    const tot = opt.seg.reduce((a, b) => a + b, 0);
    return opt.eids.map((e, j) => ({ e, r: opt.seg[j] })).sort((a, b) => b.r - a.r).slice(0, top).map(({ e, r }) => {
      const s = g.edges[e], why = [];
      if (s.curv > 60) why.push(`sharp curves (${s.curv.toFixed(0)} deg/km)`);
      if (s.grad > 3) why.push(`steep gradient (${s.grad.toFixed(1)}%)`);
      if (s.median > 1.2) why.push(`${s.median.toFixed(1)} median openings/km (U-turn & wrong-side conflicts)`);
      if (s.junc > 2.5) why.push(`dense junctions (${s.junc.toFixed(1)}/km)`);
      if (s.lit === 0 && tb !== "day") why.push("unlit stretch after dark");
      if (s.market) why.push("market zone (pedestrians, parked vehicles)");
      if (s.blackspot) why.push("on public black-spot list");
      if (hotspots && hotspots.length && s.x1 !== undefined) {
        const mx = (s.x1 + s.x2) / 2, my = (s.y1 + s.y2) / 2; let best = null, bd = 1e9;
        hotspots.forEach((h) => { const dd = Math.hypot(h.x_km - mx, h.y_km - my); if (dd < bd) { bd = dd; best = h; } });
        if (bd < 1.2) why.push(`fleet hotspot #${best.rank}: ${best.harsh_brakes} harsh brakes, ${best.near_misses} near-misses`);
      }
      return { eid: e, cls: s.cls, km: s.len, share: r / tot, reasons: why.length ? why : ["elevated estimated event rate"] };
    });
  };
  RM.compareRoutes = function (g, fast, alt, tb, hotspots) {   // which risky segments of the fastest route does the alternative really avoid?
    const altSet = new Set(alt ? alt.eids : []), top = RM.explain(g, fast, tb, hotspots, 3);
    top.forEach((x) => (x.avoided = alt ? !altSet.has(x.eid) : false));
    const shared = fast.eids.filter((e) => altSet.has(e)), sharedKm = shared.reduce((a, e) => a + g.edges[e].len, 0);
    return { top, sharedKm, avoided: top.filter((x) => x.avoided).length };
  };
  RM.postTrip = function (expCrashPerTrip, crashScale, crashes, nearMisses) {
    const expSevere = expCrashPerTrip / crashScale, obs = crashes + nearMisses, p = obs > 0 ? RM.poissonSf(obs, expSevere) : 1;
    return { expSevere, obs, p, verdict: p < 0.05 ? "excess severe events flagged: review route and segments" : "no excess-event flag (monitoring only; not a validation of the model)" };
  };

  RM.noRouteCause = function (g, o, d, banned) {
    if (!g.adj.has(o) || !g.adj.has(d)) return "network_unreachable";
    return RM.dijkstra(g, o, d, (e) => g.edges[e].time) ? (banned && banned.size ? "blocked_by_restrictions" : "network_unreachable") : "network_unreachable";
  };

  // ------------------------------------------------------------------ simulated fleet region (trained model export)
  RM.loadSim = function (D) {
    const col = Object.fromEntries(D.edge_cols.map((c, i) => [c, i]));
    const edges = D.edges.map((r) => ({ id: r[col.id], u: r[col.u], v: r[col.v], cls: r[col.cls], len: r[col.len], time: r[col.time],
      curv: r[col.curv], junc: r[col.junc], median: r[col.median], lit: r[col.lit], grad: r[col.grad], market: r[col.market],
      blackspot: r[col.blackspot], noentry: r[col.noentry], x1: r[col.x1], y1: r[col.y1], x2: r[col.x2], y2: r[col.y2] }));
    const g = RM.makeGraph(D.nodes, edges);
    g.noEntry = new Set(edges.filter((e) => e.noentry).map((e) => e.id));
    g.cache = {};
    g.context = function (ctx) {
      if (g.cache[ctx]) return g.cache[ctx];
      const C = D.contexts[ctx], tb = ctx.split("/")[0], U = D.unc;
      let mult;
      if (C.mult_b64) {                         // the Python engine's exact draws (int16 log-quantised) -> identical decisions
        const bin = typeof atob === "function" ? Uint8Array.from(atob(C.mult_b64), (c) => c.charCodeAt(0)) : new Uint8Array(Buffer.from(C.mult_b64, "base64"));
        const q = new Int16Array(bin.buffer, bin.byteOffset, bin.byteLength / 2), m = new Float64Array(q.length);
        for (let i = 0; i < q.length; i++) m[i] = Math.exp(q[i] / C.mult_q);
        mult = { m, S: C.mult_shape[0], nE: C.mult_shape[1] };
      } else {
        const sd = edges.map((e, i) => Math.sqrt(U.phi_blend[tb] * U.shrink[i] + C.boot_sd[i] ** 2 + U.extra_sd[i] ** 2));
        const seed = 1000 + 10 * ["day", "evening", "night"].indexOf(tb) + ["clear", "rain", "fog"].indexOf(ctx.split("/")[1]);
        mult = RM.multiplierDraws(edges.length, sd, U.cls_codes, U.n_cls, C.sd_ctx, U.S, seed);
      }
      return (g.cache[ctx] = { rate: C.rate, ref: C.ref, mult });
    };
    return g;
  };
  RM.decide = function (g, o, d, ctx, policy, extraBanned) {
    const C = g.context(ctx), tb = ctx.split("/")[0];
    const banned = new Set(tb !== "night" && g.noEntry ? g.noEntry : []); (extraBanned || []).forEach((e) => banned.add(e));
    const opts = RM.candidateRoutes(g, o, d, C.rate, banned).map((p) => RM.scoreRoute(g, p, C.rate, C.mult));
    opts.forEach((x) => { x.ri = RM.riskIndex(x.point, C.ref); });
    const R = RM.recommend(opts, policy.maxExtra, policy.minCut, policy.pReq);
    R.opts = opts; R.ctx = ctx; R.tb = tb; R.ref = C.ref; R.consistent = RM.isConsistent(R);
    if (R.decision === "no_legal_route") R.cause = RM.noRouteCause(g, o, d, banned);
    return R;
  };

  // ------------------------------------------------------------------ real roads: OpenStreetMap + Open-Meteo
  const HIGHWAY = /^(motorway|trunk|primary|secondary|tertiary)(_link)?$/;
  RM.overpassQuery = (b) => `[out:json][timeout:90];(way["highway"~"^(motorway|trunk|primary|secondary|tertiary)(_link)?$"](${b.s},${b.w},${b.n},${b.e}););(._;>;);out body;`;
  function hav(a, b) { const R = 6371, t = Math.PI / 180, dl = (b.lat - a.lat) * t, dn = (b.lon - a.lon) * t;
    const x = Math.sin(dl / 2) ** 2 + Math.cos(a.lat * t) * Math.cos(b.lat * t) * Math.sin(dn / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); }
  function bearing(a, b) { const t = Math.PI / 180, y = Math.sin((b.lon - a.lon) * t) * Math.cos(b.lat * t),
    x = Math.cos(a.lat * t) * Math.sin(b.lat * t) - Math.sin(a.lat * t) * Math.cos(b.lat * t) * Math.cos((b.lon - a.lon) * t); return Math.atan2(y, x) / t; }
  const ONE = new Set(["yes", "true", "1"]), REV = new Set(["-1", "reverse"]);
  RM.wayDirection = function (t) {                 // OSM oneway semantics (Key:oneway): 1 forward, -1 reverse, 0 both
    const o = (t.oneway || "").toLowerCase();
    if (ONE.has(o)) return 1; if (REV.has(o)) return -1; if (o === "no" || o === "false" || o === "0") return 0;
    if (["roundabout", "circular"].includes((t.junction || "").toLowerCase())) return 1;   // implied oneway
    if ((t.highway || "").startsWith("motorway")) return 1;                                // implied oneway
    return 0;
  };
  RM.accessBlocked = function (t) {                // returns a reason string if heavy goods vehicles may not use the way
    const ok = (v) => ["yes", "designated", "permissive", "destination", "delivery"].includes((v || "").toLowerCase());
    if ((t.hgv || "").toLowerCase() === "no") return "hgv=no";
    if ((t.goods || "").toLowerCase() === "no" && !ok(t.hgv)) return "goods=no";
    if ((t.motor_vehicle || "").toLowerCase() === "no" && !ok(t.hgv)) return "motor_vehicle=no";
    if (["no", "private"].includes((t.access || "").toLowerCase()) && !ok(t.hgv) && !ok(t.motor_vehicle)) return "access=" + t.access;
    return null;
  };
  const UNSUPPORTED = ["maxweight", "maxheight", "maxaxleload", "maxlength", "maxwidth", "hgv:conditional", "access:conditional", "maxweight:hgv"];
  RM.buildOsmGraph = function (osm, opts) {
    const o = Object.assign({ center: { lat: 25.4358, lon: 81.8463 }, urbanKm: 6, speed: { NH: 65, SH: 50, MDR: 38, URBAN: 22 } }, opts || {});
    const nodeLL = new Map(), ways = [], stats = { ways_total: 0, ways_used: 0, skipped: {}, oneway: 0, reverse_oneway: 0, roundabout: 0, unsupported_tagged_edges: 0,
      lit_tagged_km: 0, lit_assumed_km: 0, osm_base: (osm.osm3s && osm.osm3s.timestamp_osm_base) || null };
    for (const el of osm.elements || []) {
      if (el.type === "node") nodeLL.set(el.id, { lat: el.lat, lon: el.lon });
      else if (el.type === "way" && el.tags && HIGHWAY.test(el.tags.highway || "") && el.nodes && el.nodes.length > 1) {
        stats.ways_total++; const why = RM.accessBlocked(el.tags);
        if (why) { stats.skipped[why] = (stats.skipped[why] || 0) + 1; continue; }
        ways.push(el);
      }
    }
    stats.ways_used = ways.length;
    const use = new Map();
    ways.forEach((w) => w.nodes.forEach((n, i) => use.set(n, (use.get(n) || 0) + (i === 0 || i === w.nodes.length - 1 ? 2 : 1))));
    const isJ = (n) => (use.get(n) || 0) >= 2;
    const kx = 111.32 * Math.cos(o.center.lat * Math.PI / 180), ky = 110.57;
    const nodes = new Map(), edges = [];
    const addNode = (id) => { if (!nodes.has(id)) { const ll = nodeLL.get(id); nodes.set(id, { id: String(id), lat: ll.lat, lon: ll.lon,
      x: (ll.lon - o.center.lon) * kx, y: (ll.lat - o.center.lat) * ky }); } };
    for (const w of ways) {
      const t = w.tags, hw = t.highway.replace("_link", ""), ref = (t.ref || "").toUpperCase(), dir = RM.wayDirection(t);
      const warn = UNSUPPORTED.filter((k) => t[k] !== undefined).map((k) => `${k}=${t[k]}`);
      if (dir === 1) stats.oneway++; if (dir === -1) stats.reverse_oneway++; if (["roundabout", "circular"].includes(t.junction)) stats.roundabout++;
      let cur = [w.nodes[0]];
      for (let i = 1; i < w.nodes.length; i++) {
        cur.push(w.nodes[i]);
        if (i === w.nodes.length - 1 || isJ(w.nodes[i])) {
          const ids = cur.filter((n) => nodeLL.has(n)), pts = ids.map((n) => nodeLL.get(n));
          if (pts.length >= 2) {
            let len = 0, turn = 0;
            for (let k = 1; k < pts.length; k++) len += hav(pts[k - 1], pts[k]);
            for (let k = 2; k < pts.length; k++) {
              if (hav(pts[k - 2], pts[k - 1]) < 0.005 || hav(pts[k - 1], pts[k]) < 0.005) continue;
              let dlt = Math.abs(bearing(pts[k - 1], pts[k]) - bearing(pts[k - 2], pts[k - 1])); if (dlt > 180) dlt = 360 - dlt; turn += dlt;
            }
            len = Math.max(len, 0.01);
            const mid = pts[Math.floor(pts.length / 2)], urban = hav(mid, o.center) < o.urbanKm;
            let cls = (hw === "motorway" || hw === "trunk") && /NH|AH/.test(ref) ? "NH" : hw === "motorway" || hw === "trunk" || hw === "primary" ? "SH" : "MDR";
            if (urban && cls !== "NH") cls = "URBAN";
            const ms = parseFloat((t.maxspeed || "").replace(/[^0-9.]/g, ""));
            const speed = isFinite(ms) && ms > 0 ? Math.min(ms, o.speed[cls]) : o.speed[cls];
            const litTag = t.lit === "yes" ? 1 : t.lit === "no" ? 0 : null;
            if (litTag === null) stats.lit_assumed_km += len; else stats.lit_tagged_km += len;
            if (warn.length) stats.unsupported_tagged_edges++;
            const a = ids[0], b = ids[ids.length - 1]; addNode(a); addNode(b);
            edges.push({ id: edges.length, u: String(a), v: String(b), dir, cls, len, time: len / speed * 60,
              curv: turn / len, junc: 0, median: cls === "NH" ? (dir !== 0 ? 1.5 : 0.8) : 0, lit: litTag === null ? (urban ? 1 : 0) : litTag,
              grad: 0.5, market: 0, blackspot: 0, ref: t.ref || "", name: t.name || "", highway: t.highway, wayId: w.id, speed, warn,
              prov: { lit: litTag === null ? "assumed (" + (urban ? "urban" : "rural") + ")" : "OSM tag", median: cls === "NH" ? "assumed by class" : "assumed 0",
                gradient: "assumed 0.5%", market: "not observed (0)", blackspot: "not observed (0)" },
              latlngs: pts.map((p) => [p.lat, p.lon]), x1: nodes.get(a).x, y1: nodes.get(a).y, x2: nodes.get(b).x, y2: nodes.get(b).y });
          }
          cur = [w.nodes[i]];
        }
      }
    }
    const deg = new Map(); edges.forEach((e) => { deg.set(e.u, (deg.get(e.u) || 0) + 1); deg.set(e.v, (deg.get(e.v) || 0) + 1); });
    edges.forEach((e) => { const j = (deg.get(e.u) >= 3 ? 1 : 0) + (deg.get(e.v) >= 3 ? 1 : 0); e.junc = Math.min(j / Math.max(e.len, 0.25), 8); });
    const g = RM.makeGraph([...nodes.values()], edges); g.osm = true; g.stats = stats;
    RM.markComponents(g);
    stats.nodes = g.nodes.length; stats.edges = edges.length; stats.main_component_nodes = g.mainSize; stats.components = g.nComp;
    return g;
  };
  RM.markComponents = function (g) {               // strongly connected components (iterative Tarjan); routing endpoints snap to the largest one
    let idx = 0, nComp = 0; const index = new Map(), low = new Map(), on = new Set(), st = [], comp = new Map();
    for (const n0 of g.nodes) {
      if (index.has(n0.id)) continue;
      const work = [[n0.id, 0]]; index.set(n0.id, idx); low.set(n0.id, idx); idx++; st.push(n0.id); on.add(n0.id);
      while (work.length) {
        const top = work[work.length - 1], [v, i] = top, nb = g.adj.get(v);
        if (i < nb.length) {
          top[1]++; const w = nb[i].to;
          if (!index.has(w)) { index.set(w, idx); low.set(w, idx); idx++; st.push(w); on.add(w); work.push([w, 0]); }
          else if (on.has(w)) low.set(v, Math.min(low.get(v), index.get(w)));
        } else {
          work.pop(); if (work.length) { const u = work[work.length - 1][0]; low.set(u, Math.min(low.get(u), low.get(v))); }
          if (low.get(v) === index.get(v)) { let w; do { w = st.pop(); on.delete(w); comp.set(w, nComp); } while (w !== v); nComp++; }
        }
      }
    }
    const size = new Map(); comp.forEach((c) => size.set(c, (size.get(c) || 0) + 1));
    let main = 0, best = -1; size.forEach((n, c) => { if (n > best) { best = n; main = c; } });
    g.nodes.forEach((n) => (n.comp = comp.get(n.id))); g.mainComp = main; g.mainSize = best; g.nComp = nComp;
  };
  RM.coldRates = function (g, cold, tb, weather) {     // road-features-only Poisson GLM (cold start, no fleet data)
    const f = cold.features, rate = new Array(g.edges.length);
    g.edges.forEach((e, i) => {
      const x = { curvature_deg_km: Math.min(e.curv, 250), junctions_per_km: e.junc, median_openings_per_km: e.median, lit: e.lit,
        gradient_pct: e.grad, market_zone: e.market, speed_kmph: e.speed, public_blackspot: e.blackspot,
        tb_evening: tb === "evening" ? 1 : 0, tb_night: tb === "night" ? 1 : 0, w_rain: weather === "rain" ? 1 : 0, w_fog: weather === "fog" ? 1 : 0,
        unlit_dark: e.lit === 0 && tb !== "day" ? 1 : 0 };
      let z = cold.intercept; f.forEach((k, j) => (z += cold.coef[j] * (x[k] - cold.mean[j]) / cold.scale[j]));
      rate[i] = Math.exp(z) * cold.crash_scale;
    });
    return rate;
  };
  RM.coldContext = function (g, cold, tb, weather, S = 200) {
    const rate = RM.coldRates(g, cold, tb, weather), clsNames = ["NH", "SH", "MDR", "URBAN"];
    const sd = g.edges.map(() => Math.sqrt(Math.max(cold.phi_holdout_months[tb] || 0.3, 0.15) + cold.transfer_var));
    const cls = g.edges.map((e) => Math.max(0, clsNames.indexOf(e.cls)));
    const mult = RM.multiplierDraws(g.edges.length, sd, cls, 4, 0.2, S, 4242 + ["day", "evening", "night"].indexOf(tb) * 10 + ["clear", "rain", "fog"].indexOf(weather));
    return { rate, mult };
  };
  RM.inWindow = (z, hour) => { const h = ((hour % 24) + 24) % 24; return z.start <= z.end ? h >= z.start && h < z.end : h >= z.start || h < z.end; };
  RM.edgeHitsZone = function (e, z) {              // minimum distance from the zone centre to each polyline segment <= radius
    if (!e.latlngs) return false;
    const kx = 111.32 * Math.cos(z.lat * Math.PI / 180), ky = 110.57;
    const P = e.latlngs.map(([la, lo]) => [(lo - z.lon) * kx, (la - z.lat) * ky]);
    for (let i = 0; i < P.length; i++) {
      const [x1, y1] = P[i]; if (Math.hypot(x1, y1) <= z.radiusKm) return true;
      if (i + 1 < P.length) { const [x2, y2] = P[i + 1], dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy;
        const t = L2 > 0 ? Math.max(0, Math.min(1, -(x1 * dx + y1 * dy) / L2)) : 0;
        if (Math.hypot(x1 + t * dx, y1 + t * dy) <= z.radiusKm) return true; }
    }
    return false;
  };
  RM.zoneBans = function (g, zones, hour) {        // segments inside active restriction zones at the given hour
    const banned = new Set();
    zones.filter((z) => z.active && RM.inWindow(z, hour)).forEach((z) => g.edges.forEach((e) => { if (RM.edgeHitsZone(e, z)) banned.add(e.id); }));
    return banned;
  };
  RM.enRouteConflicts = function (g, opt, zones, departHour) {   // restriction windows that open while the truck is still travelling
    const out = []; let tmin = 0;
    const overlaps = (z, h0, h1) => {               // does the restriction window intersect [h0, h1] (hours, may pass midnight)?
      if (RM.inWindow(z, h0) || RM.inWindow(z, h1)) return true;
      for (let k = Math.floor(h0); k <= Math.ceil(h1); k++) if (((k % 24) + 24) % 24 === z.start % 24 && k >= h0 && k <= h1) return true;
      return false; };
    opt.eids.forEach((e) => { const h0 = departHour + tmin / 60, h1 = h0 + g.edges[e].time / 60;
      zones.forEach((z) => { if (z.active && overlaps(z, h0, h1) && RM.edgeHitsZone(g.edges[e], z)) out.push({ eid: e, zone: z.name, atHour: h0 }); });
      tmin += g.edges[e].time; });
    return out;
  };
  RM.weatherFromOpenMeteo = function (j, isoHour) {     // hourly: weather_code, visibility (m), precipitation (mm)
    const H = j.hourly, i = H.time.indexOf(isoHour); if (i < 0) return null;
    const code = H.weather_code[i], vis = H.visibility ? H.visibility[i] : null, pr = H.precipitation ? H.precipitation[i] : 0;
    let w = "clear";
    if (code === 45 || code === 48 || (vis !== null && vis < 1000)) w = "fog";
    else if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82) || code >= 95 || pr >= 0.3) w = "rain";
    return { weather: w, code, visibility_m: vis, precipitation_mm: pr };
  };
  RM.decideOn = function (g, o, d, rate, mult, ref, tb, policy, banned) {
    const opts = RM.candidateRoutes(g, o, d, rate, banned).map((p) => RM.scoreRoute(g, p, rate, mult));
    opts.forEach((x) => { x.ri = RM.riskIndex(x.point, ref); });
    const R = RM.recommend(opts, policy.maxExtra, policy.minCut, policy.pReq);
    R.opts = opts; R.tb = tb; R.ref = ref; R.consistent = RM.isConsistent(R);
    if (R.decision === "no_legal_route") R.cause = RM.noRouteCause(g, o, d, banned);
    return R;
  };
  RM.nearestNode = function (g, lat, lon, mainOnly = true) {    // snaps to the largest strongly connected component by default
    let best = null, bd = 1e9; g.nodes.forEach((n) => { if (mainOnly && (g.mainComp !== undefined ? n.comp !== g.mainComp : !g.adj.get(n.id).length)) return;
      const d = hav({ lat, lon }, n); if (d < bd) { bd = d; best = n; } });
    if (best) best.snapKm = bd; return best;
  };

  if (typeof module !== "undefined" && module.exports) module.exports = RM; else root.RMEngine = RM;
})(typeof window !== "undefined" ? window : globalThis);
