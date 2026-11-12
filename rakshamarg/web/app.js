/* RakshaMarg dispatcher console v1.1. All decisions come from RMEngine (web/engine.js).
 * Simulated mode reproduces the archived Python decisions; real-roads mode is an experimental public-data adapter. */
(function () {
  "use strict";
  const RM = window.RMEngine, D = window.RM_SIM, EX = window.RM_EXAMPLES || {}, PAR = window.RM_PARITY || null, EVD = window.RM_EVIDENCE || null;
  const VERSION = "1.2", MODEL = D.meta.source_sha256_12;
  const $ = (s, el = document) => el.querySelector(s), $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 1) => (v === null || v === undefined || !isFinite(v) ? "–" : Number(v).toFixed(d));
  const LOGKEY = "rakshamarg_triplog_v11";
  const G = RM.loadSim(D);
  const S = {
    mode: "sim", policy: { maxExtra: 12, minCut: 15, pReq: 0.9 }, last: null,
    sim: { o: null, d: null, tb: "night", w: "fog", pick: "o", hot: true },
    real: { g: null, raw: null, src: null, o: null, d: null, pick: "o", when: null, wxMode: "live", wx: null, wxCache: null, cache: {}, layers: null, map: null, check: null,
      zones: [
        { name: "Example zone: city heavy-vehicle day window (illustrative, not an official notification)", lat: 25.4500, lon: 81.8350, radiusKm: 4, start: 7, end: 22, active: false },
        { name: "Example zone: Sangam / Mela-area no-vehicle zone (modelled on Magh Mela & Maha Kumbh advisories)", lat: 25.4240, lon: 81.8850, radiusKm: 3, start: 0, end: 24, active: false }],
      bbox: { s: 25.30, w: 81.55, n: 25.58, e: 82.20 } },
  };

  // ------------------------------------------------------------------ labels
  const heatCol = (t) => { const a = [31, 157, 99], b = [242, 169, 0], c = [214, 69, 69]; const [p, q, u] = t < 0.5 ? [a, b, t * 2] : [b, c, (t - 0.5) * 2];
    return `rgb(${p.map((v, i) => Math.round(v + (q[i] - v) * u)).join(",")})`; };
  const heatScale = (rate) => { const l = rate.map(Math.log), lo = RM.quantile(l, 0.05), hi = RM.quantile(l, 0.99);
    return (r) => heatCol(Math.min(1, Math.max(0, (Math.log(r) - lo) / (hi - lo || 1)))); };
  const STATE = {
    switch: ["SWITCH", "switch", "Assign the recommended route."],
    keep: ["KEEP FASTEST", "keep", "No alternative meets the fleet policy. Assign the fastest route."],
    defer: ["REVIEW REQUIRED", "defer", "An alternative may have lower risk, but the model-based evidence is below the fleet's threshold. Assignment is on hold until a supervisor chooses a route."],
    enroute: ["REVIEW REQUIRED", "defer", "A configured restriction window opens while the truck would still be on the chosen route. Assignment is on hold until a supervisor reviews it."],
    blocked_by_restrictions: ["BLOCKED BY RESTRICTIONS", "no_legal_route", "Every route found between these points crosses an active configured restriction. Reschedule, change depot, or check permits."],
    network_unreachable: ["NO ROUTE IN LOADED NETWORK", "no_legal_route", "The loaded road network has no directed path between these points (data coverage or one-way limits). This is not a legal finding."] };
  const stateKey = (R) => (R.decision === "no_legal_route" ? R.cause || "network_unreachable" : R.enroute && R.enroute.length && R.decision !== "defer" ? "enroute" : R.decision);

  // ------------------------------------------------------------------ tabs & modes
  $$("nav.tabs button").forEach((b) => b.onclick = () => { $$("nav.tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab)); renderTab(b.dataset.tab); if (b.dataset.tab === "dispatch" && S.real.map) S.real.map.invalidateSize(); });
  $("#mode-sim").onclick = () => setMode("sim"); $("#mode-real").onclick = () => setMode("real");
  function setMode(m) {
    S.mode = m; $("#mode-sim").classList.toggle("on", m === "sim"); $("#mode-real").classList.toggle("on", m === "real");
    $("#simwrap").style.display = m === "sim" ? "" : "none"; $("#realwrap").style.display = m === "real" ? "" : "none";
    renderControls(); if (m === "real") initRealMap(); renderMaps(); renderDecision();
  }
  function renderTab(t) { ({ log: renderLog, hotspots: renderHotspots, analytics: renderAnalytics, evidence: renderEvidence, how: renderHow }[t] || (() => {}))(); }
  const status = (t) => { const el = $("#statusline"); if (el) el.textContent = t; };
  const newId = () => "D-" + Math.random().toString(16).slice(2, 10) + Date.now().toString(16).slice(-4);   // one id per scored decision

  // ------------------------------------------------------------------ controls
  const policyHtml = () => `<h3 style="margin-top:16px">Fleet policy</h3>
    <label for="p-me">Max extra driving time: <b id="v-me">${S.policy.maxExtra}%</b></label><input type="range" id="p-me" min="0" max="30" value="${S.policy.maxExtra}">
    <label for="p-mc">Min risk reduction (80th-percentile risk): <b id="v-mc">${S.policy.minCut}%</b></label><input type="range" id="p-mc" min="0" max="50" value="${S.policy.minCut}">
    <label for="p-pr">Evidence needed: comparison probability ≥ <b id="v-pr">${S.policy.pReq.toFixed(2)}</b></label><input type="range" id="p-pr" min="50" max="99" value="${Math.round(S.policy.pReq * 100)}">`;
  function bindPolicy(run) {
    $("#p-me").oninput = (e) => { S.policy.maxExtra = +e.target.value; $("#v-me").textContent = e.target.value + "%"; run(); };
    $("#p-mc").oninput = (e) => { S.policy.minCut = +e.target.value; $("#v-mc").textContent = e.target.value + "%"; run(); };
    $("#p-pr").oninput = (e) => { S.policy.pReq = +e.target.value / 100; $("#v-pr").textContent = S.policy.pReq.toFixed(2); run(); };
  }
  function renderControls() {
    const c = $("#controls");
    if (S.mode === "sim") {
      const exs = [["typical_switch", "Switch", "Typical switch"], ["typical_keep", "Keep", "Typical keep"], ["typical_defer", "Review", "Weak evidence"],
        ["no_legal_route", "Blocked", "Truck no-entry window"], ["selected_switch", "Switch", "Selected illustration: night fog"]].filter(([k]) => EX[k]);
      c.innerHTML = `<h3>Trip <span class="pill">simulated data</span></h3>
        <div class="row"><div><label for="s-o">Origin (node i,j)</label><input type="text" id="s-o" value="${S.sim.o || ""}" placeholder="click map or type"></div>
        <div><label for="s-d">Destination</label><input type="text" id="s-d" value="${S.sim.d || ""}" placeholder="click map or type"></div></div>
        <div class="note" id="s-step">${S.sim.pick === "o" ? "Step 1: click the map to set the origin (A)" : "Step 2: click the map to set the destination (B)"}</div>
        <div class="row"><div><label for="s-tb">Departure</label><select id="s-tb"><option value="day">Day 06–18</option><option value="evening">Evening 18–22</option><option value="night">Night 22–06</option></select></div>
        <div><label for="s-w">Weather forecast</label><select id="s-w"><option value="clear">Clear</option><option value="rain">Rain</option><option value="fog">Fog</option></select></div></div>
        <button class="btn wide" id="s-run">Score routes</button>
        <h3 style="margin-top:16px">Examples</h3><div class="ex">${exs.map(([k, t, l]) => `<button data-ex="${k}"><b>${t}</b> ${l}</button>`).join("")}</div>
        ${policyHtml()}
        <label style="margin-top:12px"><input type="checkbox" id="s-hot" ${S.sim.hot ? "checked" : ""}> Show fleet hotspots</label>`;
      $("#s-tb").value = S.sim.tb; $("#s-w").value = S.sim.w;
      $("#s-tb").onchange = (e) => { S.sim.tb = e.target.value; runSim(); }; $("#s-w").onchange = (e) => { S.sim.w = e.target.value; runSim(); };
      const typed = (k) => (e) => { const v = e.target.value.trim(); if (G.nodeById.has(v)) { S.sim[k] = v; runSim(); } else status(`Unknown node "${v}". Use i,j grid ids such as 3,7.`); };
      $("#s-o").onchange = typed("o"); $("#s-d").onchange = typed("d");
      $("#s-run").onclick = runSim; $("#s-hot").onchange = (e) => { S.sim.hot = e.target.checked; renderMaps(); };
      $$("[data-ex]").forEach((b) => b.onclick = () => loadExample(b.dataset.ex));
      bindPolicy(runSim);
    } else {
      const R_ = S.real;
      if (!R_.when) { const n = new Date(Date.now() + 5.5 * 3600e3); n.setUTCMinutes(0, 0, 0); R_.when = n.toISOString().slice(0, 16); }
      const snap = (k) => { const n = R_.g && R_[k] && R_.g.nodeById.get(R_[k]); return n ? `node ${n.id}${n.snapKm !== undefined ? ` (snapped ${Math.round(n.snapKm * 1000)} m)` : ""}` : ""; };
      c.innerHTML = `<h3>Real roads · NH-19 around Prayagraj <span class="pill">experimental</span></h3>
        <div class="note" id="r-status">${R_.g ? `Loaded ${R_.g.edges.length.toLocaleString()} road segments (${esc(R_.src)}).` : "Roads not loaded yet."}</div>
        <button class="btn wide" id="r-load">${R_.g ? "Reload roads" : "Load roads (OpenStreetMap)"}</button>
        ${R_.raw ? `<button class="btn sec wide" id="r-snap">Download dated snapshot</button>` : ""}
        ${R_.check ? `<details open><summary>Road-data check</summary><div class="note">${R_.check}</div></details>` : ""}
        <div class="row"><div><label>Origin</label><input type="text" id="r-o" value="${snap("o")}" readonly placeholder="click map"></div>
        <div><label>Destination</label><input type="text" id="r-d" value="${snap("d")}" readonly placeholder="click map"></div></div>
        <div class="note">${R_.pick === "o" ? "Step 1: click the map to set the origin (A)" : "Step 2: click the map to set the destination (B)"} · endpoints snap to the connected road network</div>
        <div class="ex" style="margin-top:8px"><button id="r-ex1"><b>Preset</b> NH-19 west → east through Prayagraj</button><button id="r-ex2"><b>Preset</b> Near Prayagraj Jn → Naini</button></div>
        <label for="r-when">Departure (IST)</label><input type="datetime-local" id="r-when" value="${R_.when}">
        <label for="r-wx">Weather</label><select id="r-wx"><option value="live">Live forecast (Open-Meteo)</option><option value="clear">Manual: clear</option><option value="rain">Manual: rain</option><option value="fog">Manual: fog</option></select>
        <div class="note" id="r-wxinfo">${wxText()}</div>
        <h3 style="margin-top:16px">Restriction zones (heavy vehicles)</h3>
        ${R_.zones.map((z, i) => `<div class="zone"><label style="margin:0"><input type="checkbox" data-z="${i}" ${z.active ? "checked" : ""}> ${esc(z.name)}</label>
          <div class="row"><div><label>Radius km</label><input type="number" min="0.5" max="20" step="0.5" data-zr="${i}" value="${z.radiusKm}"></div>
          <div><label>From h</label><input type="number" min="0" max="24" data-zs="${i}" value="${z.start}"></div><div><label>To h</label><input type="number" min="0" max="24" data-ze="${i}" value="${z.end}"></div></div></div>`).join("")}
        <button class="btn wide" id="r-run">Score routes</button>
        ${policyHtml()}`;
      $("#r-load").onclick = () => loadRoads(true); if ($("#r-snap")) $("#r-snap").onclick = downloadSnapshot;
      $("#r-ex1").onclick = () => presetReal(1); $("#r-ex2").onclick = () => presetReal(2);
      $("#r-when").onchange = (e) => { R_.when = e.target.value; refreshWeather().then(runReal); };
      $("#r-wx").value = R_.wxMode; $("#r-wx").onchange = (e) => { R_.wxMode = e.target.value; refreshWeather().then(runReal); };
      $$("[data-z]").forEach((x) => x.onchange = (e) => { R_.zones[+e.target.dataset.z].active = e.target.checked; runReal(); });
      $$("[data-zr]").forEach((x) => x.onchange = (e) => { R_.zones[+e.target.dataset.zr].radiusKm = +e.target.value; runReal(); });
      $$("[data-zs]").forEach((x) => x.onchange = (e) => { R_.zones[+e.target.dataset.zs].start = +e.target.value; runReal(); });
      $$("[data-ze]").forEach((x) => x.onchange = (e) => { R_.zones[+e.target.dataset.ze].end = +e.target.value; runReal(); });
      $("#r-run").onclick = runReal; bindPolicy(runReal);
    }
  }

  // ------------------------------------------------------------------ simulated region
  const xs = D.nodes.map((n) => n.x), ys = D.nodes.map((n) => n.y), X0 = Math.min(...xs) - 1, X1 = Math.max(...xs) + 1, Y0 = Math.min(...ys) - 1, Y1 = Math.max(...ys) + 1;
  const K = 900 / (X1 - X0), WW = 900, HH = (Y1 - Y0) * K, sx = (x) => (x - X0) * K, sy = (y) => (Y1 - y) * K;
  const clsW = { NH: 4.2, SH: 3.4, GHAT: 2.8, URBAN: 2.2, MDR: 1.9 };
  function renderSimMap() {
    const svg = $("#simsvg"); svg.setAttribute("viewBox", `0 0 ${WW} ${HH}`);
    const ctx = `${S.sim.tb}/${S.sim.w}`, rate = G.context(ctx).rate, col = heatScale(rate), R = S.last && S.last.mode === "sim" ? S.last.R : null;
    let h = G.edges.map((e) => `<line x1="${sx(e.x1).toFixed(1)}" y1="${sy(e.y1).toFixed(1)}" x2="${sx(e.x2).toFixed(1)}" y2="${sy(e.y2).toFixed(1)}" stroke="${col(rate[e.id])}" stroke-width="${clsW[e.cls]}" stroke-linecap="round" opacity="0.55"${e.noentry && S.sim.tb !== "night" ? ' stroke-dasharray="3 3"' : ""}/>`).join("");
    const line = (eids, c, w, dash) => eids.map((id) => { const e = G.edges[id]; return `<line x1="${sx(e.x1)}" y1="${sy(e.y1)}" x2="${sx(e.x2)}" y2="${sy(e.y2)}" stroke="${c}" stroke-width="${w}" stroke-linecap="round"${dash ? ' stroke-dasharray="7 5"' : ""}/>`; }).join("");
    if (R && R.decision !== "no_legal_route") {
      if (R.considered) h += line(R.considered.eids, R.decision === "switch" ? "var(--green)" : "#E0A100", 7);
      h += line(R.fastest.eids, R.decision === "switch" ? "#C93A3A" : "var(--ink)", R.decision === "switch" ? 3.5 : 5, R.decision !== "keep");
      RM.explain(G, R.fastest, R.tb, D.hotspots).forEach((x) => { const e = G.edges[x.eid], mx = sx((e.x1 + e.x2) / 2), my = sy((e.y1 + e.y2) / 2);
        h += `<path d="M${mx} ${my - 10} L${mx + 9} ${my + 7} L${mx - 9} ${my + 7} Z" fill="#F2A900" stroke="#1B2430" stroke-width="1.5"/>`; });
    }
    if (S.sim.hot) D.hotspots.slice(0, 8).forEach((hs) => { h += `<circle cx="${sx(hs.x_km)}" cy="${sy(hs.y_km)}" r="13" fill="none" stroke="var(--ink)" stroke-width="1.6"/><text x="${sx(hs.x_km)}" y="${sy(hs.y_km) + 4}" text-anchor="middle" font-size="11" font-weight="700" fill="var(--ink)">${hs.rank}</text>`; });
    [["o", "A", "#1B2430"], ["d", "B", "#2C6E9B"]].forEach(([k, t, c]) => { const n = S.sim[k] && G.nodeById.get(S.sim[k]); if (n) h += `<circle cx="${sx(n.x)}" cy="${sy(n.y)}" r="11" fill="${c}" stroke="#fff" stroke-width="2"/><text x="${sx(n.x)}" y="${sy(n.y) + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">${t}</text>`; });
    [["NH corridor", 1, 15], ["Urban core", 2.2, 2.6], ["Ghat section", 33, 27.2], ["SH", 20.6, 26.6]].forEach(([t, x, y]) => { h += `<text x="${sx(x)}" y="${sy(y)}" font-size="13" font-weight="700" fill="var(--ink2)" paint-order="stroke" stroke="var(--surf2)" stroke-width="4">${t}</text>`; });
    svg.innerHTML = h;
    $("#maphint").innerHTML = `<span class="lg"><span class="sw" style="background:linear-gradient(90deg,#1F9D63,#F2A900,#D64545)"></span>segment risk (${ctx.replace("/", ", ")})</span>
      <span class="lg"><span class="sw" style="background:#C93A3A"></span>fastest</span><span class="lg"><span class="sw" style="background:var(--green)"></span>recommended</span>
      <span class="lg"><span class="sw" style="background:#E0A100"></span>alternative under review</span><span class="lg">▲ top risk segments</span><span class="lg">dashed = truck no-entry 06–22</span>
      <span class="lg pill">Simulated region</span><span class="lg" id="statusline" role="status"></span>`;
  }
  $("#simsvg").addEventListener("click", (ev) => {
    const svg = $("#simsvg"), pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    let best = null, bd = 1e9; G.nodes.forEach((n) => { const d = Math.hypot(sx(n.x) - p.x, sy(n.y) - p.y); if (d < bd) { bd = d; best = n; } });
    S.sim[S.sim.pick] = best.id; S.sim.pick = S.sim.pick === "o" ? "d" : "o"; renderControls(); if (S.sim.o && S.sim.d && S.sim.o !== S.sim.d) runSim(); else renderMaps();
  });
  function runSim() {
    if (!S.sim.o || !S.sim.d) { renderMaps(); return; }
    if (S.sim.o === S.sim.d) { renderMaps(); status("Origin and destination are the same node."); return; }
    const ctx = `${S.sim.tb}/${S.sim.w}`, t0 = performance.now(), R = RM.decide(G, S.sim.o, S.sim.d, ctx, S.policy);
    S.last = { id: newId(), mode: "sim", R, ctx, o: S.sim.o, d: S.sim.d, ms: performance.now() - t0, crashScale: D.meta.model_crash_scale, g: G };
    renderMaps(); renderDecision();
  }
  function loadExample(k) {
    const c = EX[k]; S.sim.o = c.o; S.sim.d = c.d; [S.sim.tb, S.sim.w] = c.ctx.split("/"); S.policy = { maxExtra: 12, minCut: 15, pReq: 0.9 };
    renderControls(); runSim();
  }

  // ------------------------------------------------------------------ real roads (experimental public-data adapter)
  function initRealMap() {
    if (S.real.map || typeof L === "undefined") { if (typeof L === "undefined") $("#rmap").innerHTML = `<div class="banner" style="margin:20px">Map library could not load (offline?). Real-roads mode needs an internet connection; the simulated fleet region works offline.</div>`; return; }
    const b = S.real.bbox; S.real.map = L.map("rmap", { preferCanvas: true }).fitBounds([[b.s, b.w], [b.n, b.e]]);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(S.real.map);
    S.real.layers = { net: L.layerGroup().addTo(S.real.map), route: L.layerGroup().addTo(S.real.map), zones: L.layerGroup().addTo(S.real.map), marks: L.layerGroup().addTo(S.real.map) };
    L.rectangle([[b.s, b.w], [b.n, b.e]], { color: "#2C6E9B", weight: 1, fill: false, dashArray: "4 4" }).addTo(S.real.map);
    S.real.map.on("click", (ev) => { if (!S.real.g) return; const n = RM.nearestNode(S.real.g, ev.latlng.lat, ev.latlng.lng); if (!n) return; S.real[S.real.pick] = n.id;
      S.real.pick = S.real.pick === "o" ? "d" : "o"; renderControls(); if (S.real.o && S.real.d && S.real.o !== S.real.d) runReal(); else renderMaps(); });
    setTimeout(() => S.real.map.invalidateSize(), 50);
  }
  async function fetchT(url, opt, ms) { const ac = new AbortController(), t = setTimeout(() => ac.abort(), ms); try { return await fetch(url, Object.assign({ signal: ac.signal }, opt)); } finally { clearTimeout(t); } }
  async function loadRoads(forceLive) {
    const st = (t) => { const el = $("#r-status"); if (el) el.textContent = t; };
    let json = null; const reload = forceLive && S.real.g;     // first load prefers the saved dated snapshot; "Reload roads" fetches live
    if (!reload) {
      try { const r = await fetch("data/nh19_osm_snapshot.json"); if (r.ok) { json = await r.json(); S.real.src = "saved OpenStreetMap snapshot" + (json.osm3s && json.osm3s.timestamp_osm_base ? ", data as of " + json.osm3s.timestamp_osm_base.slice(0, 10) : ""); } } catch (e) {}
    }
    if (!json) {
      const q = RM.overpassQuery(S.real.bbox);
      for (const url of ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]) {
        try { st("Downloading roads from OpenStreetMap (" + new URL(url).host + ")… this can take 10–60 s.");
          const r = await fetchT(url, { method: "POST", body: "data=" + encodeURIComponent(q), headers: { "Content-Type": "application/x-www-form-urlencoded" } }, 100e3);
          if (!r.ok) throw new Error("HTTP " + r.status); json = await r.json(); S.real.raw = json;
          S.real.src = "live OpenStreetMap, data as of " + ((json.osm3s && json.osm3s.timestamp_osm_base) || new Date().toISOString()).slice(0, 16).replace("T", " ");
          break;
        } catch (e) { st("OpenStreetMap server busy (" + e.message + "), trying another…"); }
      }
    }
    if (!json) { st("Could not reach OpenStreetMap right now. Please retry in a minute (public Overpass servers are sometimes busy)."); return; }
    st("Building road graph…"); await new Promise((r) => setTimeout(r, 20));
    S.real.g = RM.buildOsmGraph(json); S.real.cache = {}; S.real.o = S.real.d = null;
    S.real.check = roadCheck(S.real.g);
    await refreshWeather(); renderControls(); renderMaps(); presetReal(1);
  }
  function presetNodes(k) {
    const g = S.real.g; if (!g) return null;
    if (k === 1) { const core = new Set(); g.edges.filter((e) => e.cls === "NH").forEach((e) => [e.u, e.v].forEach((id) => { const n = g.nodeById.get(id); if (n.comp === g.mainComp) core.add(n); }));
      const ends = [...core].sort((a, b) => a.lon - b.lon); if (ends.length < 2) return null; ends[0].snapKm = 0; ends[ends.length - 1].snapKm = 0; return [ends[0], ends[ends.length - 1]]; }
    const a = RM.nearestNode(g, 25.4454, 81.8264), b = RM.nearestNode(g, 25.3900, 81.8800); return a && b ? [a, b] : null;
  }
  function roadCheck(g) {
    const s = g.stats, skipped = Object.entries(s.skipped).map(([k, v]) => `${k}: ${v}`).join(", ") || "none";
    const ok = [1, 2].map((k) => { const p = presetNodes(k); return p && RM.dijkstra(g, p[0].id, p[1].id, (e) => g.edges[e].time) ? "✓" : "✗"; });
    return `OSM data as of ${esc(s.osm_base || "unknown")}. ${s.ways_used.toLocaleString()} of ${s.ways_total.toLocaleString()} road ways used; excluded for heavy vehicles: ${esc(skipped)}.
      One-way ways ${s.oneway} (reverse ${s.reverse_oneway}), roundabouts ${s.roundabout}. Segments with unsupported limits (weight, height…) flagged: ${s.unsupported_tagged_edges}.
      Connected core: ${(100 * g.mainSize / Math.max(g.nodes.length, 1)).toFixed(0)}% of junctions (${s.components} components). Presets reachable: west→east ${ok[0]}, Jn→Naini ${ok[1]}.
      Not modelled: turn restrictions, conditional access, weight/height limits (flagged for operator verification).`;
  }
  function downloadSnapshot() {
    const blob = new Blob([JSON.stringify(S.real.raw)], { type: "application/json" }), a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "nh19_osm_snapshot.json"; a.click();
  }
  function wxText() {
    const R_ = S.real; if (R_.wxMode !== "live") return "Manual weather: " + R_.wxMode + " (set by dispatcher).";
    if (!R_.wx) return "Live forecast loads with the roads (Open-Meteo point forecast for Prayagraj).";
    if (R_.wx.unknown) return `<b>Weather unknown</b> (${esc(R_.wx.reason)}). Scoring is paused: choose a manual weather setting to continue.`;
    return `Open-Meteo point forecast for Prayagraj (25.44 N, 81.85 E), valid ${R_.when.slice(0, 13).replace("T", " ")}:00 IST, fetched ${new Date(R_.wxCache.at).toLocaleTimeString()}: <b>${R_.wx.weather}</b>
      (code ${R_.wx.code}, visibility ${R_.wx.visibility_m === null ? "–" : Math.round(R_.wx.visibility_m) + " m"}, rain ${fmt(R_.wx.precipitation_mm)} mm). One point is used for the whole corridor (prototype approximation).`;
  }
  async function refreshWeather() {
    const R_ = S.real; if (R_.wxMode !== "live") { R_.wx = null; const el = $("#r-wxinfo"); if (el) el.innerHTML = wxText(); return; }
    const u = "https://api.open-meteo.com/v1/forecast?latitude=25.4358&longitude=81.8463&hourly=weather_code,visibility,precipitation&timezone=Asia%2FKolkata&past_days=7&forecast_days=16";
    try {
      if (!R_.wxCache || Date.now() - R_.wxCache.at > 30 * 60e3) {
        let r = null; for (let i = 0; i < 2 && !(r && r.ok); i++) { try { r = await fetchT(u, {}, 15e3); } catch (e) { r = null; } }
        if (!r || !r.ok) throw new Error(r ? "HTTP " + r.status : "no response");
        R_.wxCache = { json: await r.json(), at: Date.now() };
      }
      R_.wx = RM.weatherFromOpenMeteo(R_.wxCache.json, R_.when.slice(0, 13) + ":00") || { unknown: true, reason: "departure outside the forecast window" };
    } catch (e) { R_.wx = { unknown: true, reason: "forecast unavailable: " + e.message }; }
    const el = $("#r-wxinfo"); if (el) el.innerHTML = wxText();
  }
  function realCtx() {
    const R_ = S.real, hour = +R_.when.slice(11, 13), hf = hour + (+R_.when.slice(14, 16) || 0) / 60, tb = RM.timeBucket(hour);
    let w = R_.wxMode; if (w === "live") { if (!R_.wx || R_.wx.unknown) return { unknown: true, tb, hour, hf }; w = R_.wx.weather; }
    const key = tb + "/" + w;
    if (!R_.cache[key]) {
      const cc = RM.coldContext(R_.g, D.cold, tb, w), rng = RM.mulberry32(7), pts = [], ns = R_.g.nodes.filter((n) => n.comp === R_.g.mainComp);
      for (let i = 0; i < 40 && ns.length > 2; i++) { const a = ns[Math.floor(rng() * ns.length)], b = ns[Math.floor(rng() * ns.length)];
        const p = RM.dijkstra(R_.g, a.id, b.id, (e) => R_.g.edges[e].time); if (p && p.eids.length > 3) pts.push(p.eids.reduce((s, e) => s + cc.rate[e] * R_.g.edges[e].len * 1000, 0)); }
      cc.ref = pts.length ? RM.median(pts) : 1; R_.cache[key] = cc;
    }
    return { tb, w, hour, hf, ctx: key, cc: R_.cache[key] };
  }
  function presetReal(k) { const p = presetNodes(k); if (!p) { status("Preset not available in this road extract."); return; } S.real.o = p[0].id; S.real.d = p[1].id; renderControls(); runReal(); }
  function runReal() {
    const R_ = S.real; if (!R_.g || !R_.o || !R_.d || R_.o === R_.d) { renderMaps(); return; }
    const c = realCtx();
    if (c.unknown) { S.last = { mode: "real", unknownWeather: true, ctx: "weather unknown" }; renderMaps(); renderDecision(); return; }
    const banned = RM.zoneBans(R_.g, R_.zones, c.hf), t0 = performance.now();
    const R = RM.decideOn(R_.g, R_.o, R_.d, c.cc.rate, c.cc.mult, c.cc.ref, c.tb, S.policy, banned);
    if (R.chosen) R.enroute = RM.enRouteConflicts(R_.g, R.chosen, R_.zones, c.hf);
    S.last = { id: newId(), mode: "real", R, ctx: c.ctx, o: R_.o, d: R_.d, ms: performance.now() - t0, crashScale: D.cold.crash_scale, banned: banned.size, g: R_.g };
    renderMaps(); renderDecision();
  }
  function renderRealMap() {
    const R_ = S.real; if (!R_.map) return; const Ly = R_.layers; Ly.net.clearLayers(); Ly.route.clearLayers(); Ly.zones.clearLayers(); Ly.marks.clearLayers();
    const hf = +R_.when.slice(11, 13) + (+R_.when.slice(14, 16) || 0) / 60;
    R_.zones.forEach((z) => { const on = z.active && RM.inWindow(z, hf);
      L.circle([z.lat, z.lon], { radius: z.radiusKm * 1000, color: on ? "#C93A3A" : "#7A8596", weight: 1.5, dashArray: on ? null : "4 4", fillOpacity: on ? 0.08 : 0 }).bindTooltip(z.name + (on ? " (active at departure)" : z.active ? " (enabled, outside its window)" : " (disabled)")).addTo(Ly.zones); });
    if (R_.g) {
      const c = realCtx(), col = c.unknown ? () => "#8A94A3" : heatScale(c.cc.rate);
      R_.g.edges.forEach((e) => L.polyline(e.latlngs, { color: c.unknown ? "#8A94A3" : col(c.cc.rate[e.id]), weight: e.cls === "NH" ? 4 : 2.5, opacity: e.warn.length ? 0.9 : 0.6, dashArray: e.dir ? null : null })
        .bindTooltip(`${esc(e.ref || e.highway)}${e.name ? " · " + esc(e.name) : ""} · ${e.len.toFixed(1)} km${e.dir ? " · one-way" : ""}${e.warn.length ? " · verify: " + esc(e.warn.join(", ")) : ""}`).addTo(Ly.net));
      const R = S.last && S.last.mode === "real" && S.last.R ? S.last.R : null;
      const draw = (o, color, w, dash) => o.eids.forEach((id) => L.polyline(R_.g.edges[id].latlngs, { color, weight: w, opacity: 0.95, dashArray: dash }).addTo(Ly.route));
      if (R && R.decision !== "no_legal_route") { if (R.considered) draw(R.considered, R.decision === "switch" ? "#1F9D63" : "#E0A100", 8);
        draw(R.fastest, R.decision === "switch" ? "#C93A3A" : "#1B2430", 4, R.decision === "keep" ? null : "8 6"); }
      [["o", "A", "#1B2430"], ["d", "B", "#2C6E9B"]].forEach(([k, t, cl]) => { const n = R_[k] && R_.g.nodeById.get(R_[k]);
        if (n) L.marker([n.lat, n.lon], { icon: L.divIcon({ html: `<div style="background:${cl};color:#fff;border:2px solid #fff;border-radius:50%;width:24px;height:24px;line-height:20px;text-align:center;font-weight:700">${t}</div>`, className: "", iconSize: [24, 24] }) }).addTo(Ly.marks); });
    }
    $("#maphint").innerHTML = `<span class="lg"><span class="sw" style="background:linear-gradient(90deg,#1F9D63,#F2A900,#D64545)"></span>experimental relative risk (road features + weather)</span>
      <span class="lg"><span class="sw" style="background:#C93A3A"></span>fastest</span><span class="lg"><span class="sw" style="background:#1F9D63"></span>recommended</span>
      <span class="lg"><span class="sw" style="background:#E0A100"></span>alternative under review</span><span class="lg">red circles = active restriction zones</span>
      <span class="lg pill">Real OpenStreetMap roads · experimental</span><span class="lg" id="statusline" role="status"></span>`;
  }
  function renderMaps() { if (S.mode === "sim") renderSimMap(); else renderRealMap(); }

  // ------------------------------------------------------------------ decision card, verified explanations, briefs
  const HI = [[/sharp curves/, "तीखे मोड़"], [/steep gradient/, "तीखी ढलान"], [/median openings/, "बार-बार मीडियन कट"], [/dense junctions/, "घने चौराहे"],
    [/unlit/, "बिना रोशनी वाले हिस्से"], [/market zone/, "बाज़ार क्षेत्र"], [/black-spot/, "ब्लैक स्पॉट"], [/hotspot/, "दुर्घटना-संभावित हिस्सा (फ्लीट हॉटस्पॉट)"], [/elevated/, "अधिक जोखिम वाला हिस्सा"]];
  const EN = [[/sharp curves/, "sharp curves"], [/steep gradient/, "steep gradients"], [/median openings/, "frequent median cuts"], [/dense junctions/, "dense junctions"],
    [/unlit/, "unlit stretches"], [/market zone/, "a market zone"], [/black-spot/, "a listed black spot"], [/hotspot/, "a fleet hotspot"], [/elevated/, "higher-risk segments"]];
  const keys = (items, map) => { const out = []; items.forEach((x) => x.reasons.forEach((r) => map.forEach(([re, t]) => { if (re.test(r) && !out.includes(t)) out.push(t); }))); return out.slice(0, 3); };
  function briefs(R, w, tb, cmp, g, mode) {
    const ch = R.chosen, km = ch.km.toFixed(0), mn = ch.time.toFixed(0), extra = (R.chosen.time - R.fastest.time).toFixed(0);
    const own = RM.explain(g, ch, tb, (mode || S.last.mode) === "sim" ? D.hotspots : []), av = cmp.top.filter((x) => x.avoided);
    let e, h;
    if (R.decision === "switch") {
      e = `Take the recommended route (${km} km, about ${mn} min; about ${extra} min more than the fastest).` + (av.length ? ` It avoids ${av.length} of the 3 highest-risk segments on the fastest route (${keys(av, EN).join(", ")}).` : " Its overall estimated risk is lower; the highest-risk segments are shared.");
      h = `सुझाया गया रूट लें (${km} किमी, लगभग ${mn} मिनट; सबसे तेज़ रूट से लगभग ${extra} मिनट ज़्यादा)।` + (av.length ? ` यह तेज़ रूट के ${av.length} सबसे जोखिम वाले हिस्सों (${keys(av, HI).join(", ")}) से बचता है।` : "");
    } else { e = `Take the fastest route (${km} km, about ${mn} min).`; h = `सबसे तेज़ रूट लें (${km} किमी, लगभग ${mn} मिनट)।`; }
    const ownEn = keys(own, EN), ownHi = keys(own, HI);
    if (ownEn.length) { e += ` On your route, take extra care at: ${ownEn.join(", ")}.`; h += ` आपके रूट पर इन जगहों पर विशेष सावधानी रखें: ${ownHi.join(", ")}।`; }
    if (w === "fog") { e += " In fog: keep a much longer following distance than usual, use low beam and fog lamps, never stop on the carriageway."; h += " कोहरे में आगे की गाड़ी से सामान्य से कहीं अधिक दूरी रखें, लो-बीम/फॉग लैंप का प्रयोग करें और सड़क पर गाड़ी न रोकें।"; }
    else if (w === "rain") { e += " In rain: slow down on curves and avoid hard braking."; h += " बारिश में मोड़ों पर गति कम रखें और अचानक ब्रेक न लगाएं।"; }
    if (tb !== "day") { e += " After dark, watch for unlit stretches and median openings."; h += " रात में बिना रोशनी वाले हिस्सों और मीडियन कट पर सावधान रहें।"; }
    return { e, h };
  }
  function provenance(g, opt) {
    let tagged = 0, assumed = 0; const warn = new Set();
    opt.eids.forEach((id) => { const e = g.edges[id]; if (e.prov.lit === "OSM tag") tagged += e.len; else assumed += e.len; e.warn.forEach((w) => warn.add(w)); });
    return `<details open><summary>Input provenance for the shown route</summary><ul class="reasons">
      <li><b>Observed (OpenStreetMap):</b> geometry, length, curvature, junctions, road class, one-way, access tags; lighting tagged on ${tagged.toFixed(1)} km.</li>
      <li><b>Assumed:</b> lighting on ${assumed.toFixed(1)} km (urban/rural rule), median openings (by road class), gradient 0.5%, no market-zone or black-spot data.</li>
      <li><b>Not modelled:</b> turn restrictions, conditional access${warn.size ? `; <b>verify on this route:</b> ${esc([...warn].join(", "))}` : "; no weight/height limits tagged on this route"}.</li></ul></details>`;
  }
  function renderDecision() {
    const el = $("#decision"), L_ = S.last;
    if (!L_ || L_.mode !== S.mode) { el.innerHTML = `<div class="dec"><b>No trip scored yet.</b><p class="note">${S.mode === "sim" ? "Pick an example on the left, or set two points." : "Load roads, then use a preset or click two points on the map."}</p></div>`; return; }
    if (L_.unknownWeather) { el.innerHTML = `<div class="dec"><span class="badge b-defer">WEATHER UNKNOWN</span><div class="msg">The forecast for this departure is unavailable, so no recommendation is made. Choose a manual weather setting to continue.</div></div>`; return; }
    const R = L_.R, w = L_.ctx.split("/")[1], real = L_.mode === "real", sk = stateKey(R), [lab, cls, msg] = STATE[sk];
    let h = real ? `<div class="banner"><b>Experimental real-roads mode.</b> Real OpenStreetMap geometry and live weather, but risk scores come from a model trained on simulated fleet data and are <b>not calibrated to real crashes</b>. Use for route comparison only, with operator verification.</div>` : "";
    h += `<div class="dec"><span class="badge b-${cls}">${lab}</span><div class="msg">${msg}</div>`;
    if (R.decision === "no_legal_route") {
      h += `<p class="note">Context: ${L_.ctx.replace("/", ", ")} · ${R.cause === "blocked_by_restrictions" ? (real ? L_.banned + " segments blocked by active zones" : "truck no-entry streets closed 06–22 (configured profile)") : "no directed path in the loaded network"}.</p>
        <button class="btn sec" id="d-log">Log as unroutable</button></div>`;
      el.innerHTML = h; $("#d-log").onclick = () => logTrip(L_, null); return;
    }
    if (sk === "enroute") h += `<div class="banner">Restriction opens en route: ${esc(R.enroute[0].zone)} at about ${String(Math.floor(R.enroute[0].atHour % 24)).padStart(2, "0")}:${String(Math.round((R.enroute[0].atHour % 1) * 60)).padStart(2, "0")}.</div>`;
    if (R.p !== null && R.p !== undefined) h += `<div class="pline">Model-based comparison probability P(lower expected risk) = ${R.p.toFixed(3)} <span class="note">(threshold ${S.policy.pReq.toFixed(2)})</span></div>`
      + (R.borderline ? `<div class="note">⚠ Borderline: within Monte-Carlo precision of the threshold; a small change in inputs could flip this decision.</div>` : "");
    const opt = (t, o, c) => `<div class="opt" style="border-color:${c}"><div><div class="t" style="color:${c}">${t}</div>
      <div class="m">${o.time.toFixed(0)} min · ${o.km.toFixed(1)} km${real ? "" : ` · ${o.confidence} confidence`}</div>
      ${real ? `<div class="m">Experimental relative score (simulator-trained)</div>` : `<div class="m">Expected crashes per 1,000 trips ${fmt(o.point, 2)} (90% band ${fmt(o.lo, 2)}–${fmt(o.hi, 2)}), simulated model</div>`}</div>
      <div class="ri" style="color:${c}">${Math.round(o.ri)}<small>${real ? "relative risk" : "risk index"}</small></div></div>`;
    h += opt("Fastest", R.fastest, R.decision === "switch" ? "var(--red)" : "var(--ink2)");
    if (R.considered) h += opt(R.decision === "switch" ? "Recommended" : "Alternative under review", R.considered, R.decision === "switch" ? "var(--green)" : "var(--amber)");
    if (R.considered) { const dt = R.considered.time - R.fastest.time, dr = (1 - R.considered.point / R.fastest.point) * 100;
      h += `<div class="note">Trade-off: ${dr >= 0 ? "−" : "+"}${Math.abs(dr).toFixed(0)}% ${real ? "relative risk score" : "expected crashes (model)"} for +${dt.toFixed(1)} min estimated extra driving time (+${(dt / R.fastest.time * 100).toFixed(1)}%).</div>`; }
    const cmp = RM.compareRoutes(L_.g, R.fastest, R.considered, R.tb, real ? [] : D.hotspots);
    h += `<h4 style="margin:12px 0 4px">Highest-risk segments on the fastest route</h4><ul class="reasons">${cmp.top.map((x) => `<li><b>${x.cls}, ${x.km.toFixed(1)} km, ${Math.round(x.share * 100)}% of route risk:</b> ${esc(x.reasons.join("; "))}${real && /median/.test(x.reasons.join()) ? " (median cuts assumed by road class)" : ""}${R.considered ? (x.avoided ? ' <span class="ok">· avoided by the alternative</span>' : " · shared with the alternative") : ""}</li>`).join("")}</ul>`;
    if (R.considered) h += `<div class="note">Shared road between the two routes: ${cmp.sharedKm.toFixed(1)} km.</div>`;
    if (real) h += provenance(L_.g, R.chosen);
    const review = sk === "defer" || sk === "enroute";
    if (!review) { const B = briefs(R, w, R.tb, cmp, L_.g); L_.brief = B;
      h += `<div class="brief"><b>Driver brief (template; to be reviewed by a fleet safety lead)</b><div>${esc(B.e)}</div><div class="hi">${esc(B.h)}</div></div>`; }
    else h += `<div class="brief"><b>Driver brief</b><div>Issued after the supervisor chooses a route.</div></div>`;
    h += `<div class="row" style="margin-top:10px"><button class="btn" id="d-log">${review ? "Send to supervisor review" : "Assign &amp; log trip"}</button>${review ? "" : '<button class="btn sec" id="d-copy">Copy brief</button>'}</div>
      <details><summary>All ${R.opts.length} candidate routes</summary><div class="tablewrap"><table><tr><th>#</th><th>Time</th><th>km</th><th>${real ? "Rel. risk" : "Risk idx"}</th><th>80th pct</th></tr>
      ${R.opts.map((o, i) => `<tr><td>${i + 1}</td><td>${o.time.toFixed(1)}</td><td>${o.km.toFixed(1)}</td><td>${Math.round(o.ri)}</td><td>${fmt(o.q, 2)}</td></tr>`).join("")}</table></div></details>
      <p class="note">${R.consistent ? '<span class="ok">✓</span> decision object consistent' : "⚠ inconsistent"} · ${R.nQual} qualifying alternative(s) · ${L_.ms.toFixed(0)} ms · context ${L_.ctx.replace("/", ", ")}${real ? "" : " · risk index is relative to this context, not a crash probability"}</p></div>`;
    el.innerHTML = h;
    $("#d-log").onclick = () => logTrip(L_, review ? null : L_.brief);
    if ($("#d-copy")) $("#d-copy").onclick = () => { navigator.clipboard && navigator.clipboard.writeText(L_.brief.e + "\n" + L_.brief.h); $("#d-copy").textContent = "Copied ✓"; };
  }

  // ------------------------------------------------------------------ trip log, supervisor review, post-trip check (T6) + search (T7)
  const getLog = () => { try { return JSON.parse(localStorage.getItem(LOGKEY) || "[]"); } catch (e) { return []; } };
  const setLog = (l) => { try { localStorage.setItem(LOGKEY, JSON.stringify(l)); return true; } catch (e) { alert("Could not save to this browser's storage (private mode or storage full). The trip was NOT logged."); return false; } };
  const pack = (o) => o ? { eids: o.eids.slice(0, 600), ri: Math.round(o.ri), exp: o.point / 1000, km: +o.km.toFixed(2), min: +o.time.toFixed(1) } : null;
  function logTrip(L_, brief) {
    const R = L_.R, sk = stateKey(R), l = getLog();
    const key = L_.id;                                // the same scored decision cannot be logged twice; re-scoring a repeat journey creates a new trip
    const dup = l.find((t) => t.key === key);
    if (dup) { $("#d-log").textContent = "Already logged as " + dup.id; $("#d-log").disabled = true; return; }
    const st = sk === "defer" || sk === "enroute" ? "pending_review" : R.decision === "no_legal_route" ? "unroutable" : "assigned";
    const entry = { id: "T-" + Math.random().toString(16).slice(2, 10), key, at: new Date().toISOString().slice(0, 16).replace("T", " "), mode: L_.mode, o: L_.o, d: L_.d, ctx: L_.ctx,
      state: sk, p: R.p === undefined ? null : R.p, borderline: !!R.borderline, status: st, assigned: st === "assigned" ? (R.decision === "switch" ? "recommended" : "fastest") : null,
      fast: pack(R.fastest), alt: pack(R.considered), crashScale: L_.crashScale, model: MODEL, policy: Object.assign({}, S.policy), brief: brief ? brief.e : null, review: null, outcome: null };
    l.unshift(entry);
    if (setLog(l)) { $("#d-log").textContent = st === "pending_review" ? "Sent to review ✓ (" + entry.id + ")" : "Logged ✓ (" + entry.id + ")"; $("#d-log").disabled = true; }
  }
  const assignedOpt = (t) => (t.assigned === "recommended" ? t.alt : t.assigned === "fastest" ? t.fast : null);
  function briefForEntry(t) {                         // regenerate the brief for the route the supervisor approved
    const [tb, w] = t.ctx.split("/"); let g = null, rate = null;
    if (t.mode === "sim") { g = G; rate = G.context(t.ctx).rate; }
    else if (S.real.g && S.real.cache[t.ctx]) { g = S.real.g; rate = S.real.cache[t.ctx].rate; }
    const pick = assignedOpt(t);
    if (!g) return { e: `Take the ${t.assigned === "recommended" ? "approved alternative" : "fastest"} route (${pick.km.toFixed(0)} km, about ${pick.min.toFixed(0)} min). Detailed brief needs the road data reloaded.`, h: "" };
    const sc = (o) => (o ? RM.scoreRoute(g, { eids: o.eids, path: [] }, rate, null) : null), fast = sc(t.fast), alt = sc(t.alt);
    const R = { decision: t.assigned === "recommended" ? "switch" : "keep", fastest: fast, considered: alt, chosen: t.assigned === "recommended" ? alt : fast };
    return briefs(R, w, tb, RM.compareRoutes(g, fast, alt, tb, t.mode === "sim" ? D.hotspots : []), g, t.mode);
  }
  function renderLog() {
    const l = getLog(), min = +(S.logMin || 0), pend = l.filter((t) => t.status === "pending_review").length;
    const rows = l.filter((t) => (assignedOpt(t) ? assignedOpt(t).ri : t.fast ? t.fast.ri : 0) >= min);
    $("#tab-log").innerHTML = `<div class="panel"><h3>Trip log · supervisor review · post-trip check</h3>
      <p class="note">Assigned trips are logged with the route and its risk score. Trips needing review stay on hold until a supervisor chooses a route (recorded with name, time and note). After a trip, observed crashes and near-misses are compared with the prediction; a flag is a monitoring signal, not proof the model is right or wrong. Stored in this browser.</p>
      <div class="kpis" style="margin-top:8px"><div class="kpi"><b>${l.length}</b><span>trips logged</span></div><div class="kpi"><b>${pend}</b><span>awaiting supervisor review</span></div>
      <div class="kpi"><b>${l.filter((t) => t.review).length}</b><span>reviews resolved</span></div><div class="kpi"><b>${l.filter((t) => t.outcome && t.outcome.p < 0.05).length}</b><span>excess-event flags</span></div></div>
      <div class="row" style="max-width:640px"><div><label for="lm">Search: minimum risk index <b id="lm-v">${min}</b></label><input type="range" id="lm" min="0" max="100" value="${min}"></div>
      <div style="display:flex;gap:8px;align-items:end"><button class="btn sec" id="lg-csv">Export CSV</button><button class="btn sec" id="lg-clr">Clear log</button></div></div>
      <div class="tablewrap" style="margin-top:10px"><table><tr><th>Trip</th><th>Logged</th><th>Mode</th><th>Context</th><th>Decision</th><th>Status</th><th>Assigned (risk idx)</th><th>Action / record</th></tr>
      ${rows.length ? rows.map((t) => { const a = assignedOpt(t);
        let act = "";
        if (t.status === "pending_review") act = `<div class="row" style="gap:4px"><input type="text" placeholder="Supervisor name" data-sv="${t.id}"><input type="text" placeholder="Note" data-sn="${t.id}"></div>
          <div class="row" style="gap:4px;margin-top:4px"><button class="btn sec" data-ap="${t.id}" data-ch="fastest">Approve fastest</button>${t.alt ? `<button class="btn sec" data-ap="${t.id}" data-ch="recommended">Approve alternative</button>` : ""}</div>`;
        else if (a && !t.outcome) act = `<span class="row" style="gap:4px"><input type="number" min="0" value="0" data-oc="${t.id}" aria-label="crashes" style="width:64px"><input type="number" min="0" value="0" data-on="${t.id}" aria-label="near-misses" style="width:64px"><button class="btn sec" data-ok="${t.id}">Record outcome</button></span><span class="note">crashes · near-misses</span>`;
        else if (t.outcome) act = `<b class="${t.outcome.p < 0.05 ? "" : "ok"}">${esc(t.outcome.verdict)}</b> <span class="note">(${t.outcome.obs} observed vs ${t.outcome.expSevere.toFixed(3)} expected; p=${t.outcome.p.toFixed(3)})</span>`;
        const rv = (t.review ? `<div class="note">Reviewed by ${esc(t.review.by)} at ${t.review.at}: ${t.review.choice}${t.review.note ? " — " + esc(t.review.note) : ""}</div>` : "")
          + (t.brief ? `<details><summary>Driver brief issued</summary><div class="note">${esc(t.brief)}</div>${t.briefHi ? `<div class="note hi">${esc(t.briefHi)}</div>` : ""}</details>` : "");
        return `<tr><td>${t.id}</td><td>${t.at}</td><td>${t.mode === "sim" ? "demo region" : "NH-19 real"}</td><td>${t.ctx}</td><td>${STATE[t.state] ? STATE[t.state][0] : t.state}</td><td>${t.status.replace("_", " ")}</td>
          <td>${a ? `${t.assigned} (<b>${a.ri}</b>)` : "–"}</td><td>${act}${rv}</td></tr>`; }).join("")
        : `<tr><td colspan="8" class="note">No trips logged yet. Score a route on the Dispatch tab and press “Assign &amp; log trip” or “Send to supervisor review”.</td></tr>`}</table></div></div>`;
    $("#lm").oninput = (e) => { S.logMin = +e.target.value; renderLog(); };
    $("#lg-clr").onclick = () => { setLog([]); renderLog(); };
    $("#lg-csv").onclick = () => {
      const cols = ["id", "logged_at", "model_version", "mode", "origin", "destination", "context", "decision", "comparison_p", "borderline", "status", "assigned_route", "assigned_segment_ids",
        "assigned_risk_index", "assigned_expected_crashes_per_trip", "assigned_km", "assigned_minutes", "fastest_risk_index", "fastest_minutes", "policy_max_extra_pct", "policy_min_cut_pct",
        "policy_p_required", "supervisor", "reviewed_at", "review_note", "outcome_crashes", "outcome_near_misses", "outcome_expected_severe", "outcome_p", "outcome_flag"];
      const rows = getLog().map((t) => { const a = assignedOpt(t) || {}, f = t.fast || {}, o = t.outcome || {}, r = t.review || {};
        return [t.id, t.at, t.model, t.mode, t.o, t.d, t.ctx, t.state, t.p, t.borderline, t.status, t.assigned, (a.eids || []).join(" "), a.ri, a.exp, a.km, a.min, f.ri, f.min,
          t.policy.maxExtra, t.policy.minCut, t.policy.pReq, r.by, r.at, r.note, o.crashes, o.nm, o.expSevere, o.p, o.verdict].map((v) => JSON.stringify(v ?? "")).join(","); });
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([[cols.join(",")].concat(rows).join("\n")], { type: "text/csv" })); a.download = "rakshamarg_trip_log.csv"; a.click(); };
    $$("[data-ap]").forEach((b) => b.onclick = () => { const id = b.dataset.ap, l2 = getLog(), t = l2.find((x) => x.id === id), by = ($(`[data-sv="${id}"]`).value || "").trim();
      if (!by) { alert("Enter the supervisor's name to record the review."); return; }
      t.review = { by, at: new Date().toISOString().slice(0, 16).replace("T", " "), choice: b.dataset.ch === "recommended" ? "approved alternative" : "approved fastest", note: ($(`[data-sn="${id}"]`).value || "").trim() };
      t.status = "assigned"; t.assigned = b.dataset.ch; const B = briefForEntry(t); t.brief = B.e; t.briefHi = B.h;
      if (setLog(l2)) renderLog(); });
    $$("[data-ok]").forEach((b) => b.onclick = () => { const id = b.dataset.ok, l2 = getLog(), t = l2.find((x) => x.id === id), a = assignedOpt(t);
      const c = +$(`[data-oc="${id}"]`).value, n = +$(`[data-on="${id}"]`).value; t.outcome = Object.assign(RM.postTrip(a.exp, t.crashScale, c, n), { crashes: c, nm: n }); if (setLog(l2)) renderLog(); });
  }

  // ------------------------------------------------------------------ hotspots, analytics, evidence, how
  function renderHotspots() {
    const f = S.hf || { cls: "", night: 0, pub: "" }; S.hf = f;
    const rows = D.hotspots.filter((h) => (!f.cls || h.road_class === f.cls) && h.night_share >= f.night && (f.pub === "" || String(h.public_blackspot) === f.pub));
    $("#tab-hotspots").innerHTML = `<div class="panel"><h3>Hotspot registry (searchable) <span class="pill">simulated data</span></h3>
      <p class="note">Fleet events weighted by severity (crash 10, near-miss 4, harsh brake 1) and recency, divided by traffic exposure, smoothed, and clustered (DBSCAN on map distance). Ranked by exposure-normalised severity. Findings about the public list are simulator findings, not discoveries on real roads.</p>
      <div class="row" style="max-width:720px"><div><label for="hf-c">Road class</label><select id="hf-c"><option value="">All</option>${[...new Set(D.hotspots.map((h) => h.road_class))].map((c) => `<option>${c}</option>`).join("")}</select></div>
      <div><label for="hf-n">Min night share</label><input type="number" id="hf-n" min="0" max="1" step="0.05" value="${f.night}"></div>
      <div><label for="hf-p">On public black-spot list</label><select id="hf-p"><option value="">Any</option><option value="1">Yes</option><option value="0">No (fleet-only)</option></select></div></div>
      <div class="tablewrap" style="margin-top:10px"><table><tr><th>Rank</th><th>Class</th><th>Crashes</th><th>Near-misses</th><th>Harsh brakes</th><th>Night share</th><th>Public list</th><th>Location (km)</th></tr>
      ${rows.map((h) => `<tr><td><b>#${h.rank}</b></td><td>${h.road_class}</td><td>${h.crashes}</td><td>${h.near_misses}</td><td>${h.harsh_brakes.toLocaleString()}</td><td>${(h.night_share * 100).toFixed(0)}%</td><td>${h.public_blackspot ? "yes" : "<b>no</b>"}</td><td>${h.x_km.toFixed(1)}, ${h.y_km.toFixed(1)}</td></tr>`).join("")}</table></div></div>`;
    $("#hf-c").value = f.cls; $("#hf-p").value = f.pub;
    $("#hf-c").onchange = (e) => { f.cls = e.target.value; renderHotspots(); }; $("#hf-n").onchange = (e) => { f.night = +e.target.value; renderHotspots(); };
    $("#hf-p").onchange = (e) => { f.pub = e.target.value; renderHotspots(); };
  }
  function lineChart(rows, key, title) {
    const groups = [...new Set(rows.map((r) => r[key]))], W = 560, H = 250, P = 40, cols = ["#1F9D63", "#2C6E9B", "#B07A00", "#C93A3A", "#7A8596"];
    const v = rows.map((r) => r.severity_score_per_1k_vkm), lo = Math.min(...v), hi = Math.max(...v);
    const X = (m) => P + (m - 1) / 11 * (W - P - 10), Y = (y) => H - 30 - (y - lo) / (hi - lo || 1) * (H - 60);
    let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img" aria-label="${esc(title)}"><text x="${P}" y="16" font-size="13" font-weight="700" fill="var(--ink)">${title}</text>`;
    "JFMAMJJASOND".split("").forEach((m, i) => (s += `<text x="${X(i + 1)}" y="${H - 10}" font-size="11" text-anchor="middle" fill="var(--ink2)">${m}</text>`));
    [lo, (lo + hi) / 2, hi].forEach((y) => (s += `<text x="${P - 6}" y="${Y(y) + 4}" font-size="11" text-anchor="end" fill="var(--ink2)">${y.toFixed(0)}</text><line x1="${P}" x2="${W - 10}" y1="${Y(y)}" y2="${Y(y)}" stroke="var(--line)"/>`));
    groups.forEach((gname, gi) => { const pts = rows.filter((r) => r[key] === gname).sort((a, b) => a.month - b.month);
      s += `<polyline fill="none" stroke="${cols[gi % 5]}" stroke-width="2.5" points="${pts.map((r) => X(r.month) + "," + Y(r.severity_score_per_1k_vkm)).join(" ")}"/>`;
      s += `<text x="${P + 10 + gi * 92}" y="34" font-size="12" fill="${cols[gi % 5]}" font-weight="700">■ ${gname}</text>`; });
    return s + "</svg>";
  }
  function renderAnalytics() {
    const l = getLog(), cnt = (k) => l.filter((t) => t.state === k).length;
    $("#tab-analytics").innerHTML = `<div class="kpis"><div class="kpi"><b>${l.length}</b><span>trips logged in this browser</span></div><div class="kpi"><b>${cnt("switch")}</b><span>switched to a lower-risk route</span></div>
      <div class="kpi"><b>${cnt("defer") + cnt("enroute")}</b><span>sent for supervisor review</span></div><div class="kpi"><b>${l.filter((t) => t.outcome && t.outcome.p < 0.05).length}</b><span>excess-event flags</span></div></div>
      <div class="cols2"><div class="panel">${lineChart(D.trend_region, "region", "Severity score per 1,000 veh-km by region (simulated year)")}</div>
      <div class="panel">${lineChart(D.trend_class, "cls", "Severity score per 1,000 veh-km by road class (simulated year)")}</div></div>
      <p class="note">Severity score = crashes × 10 + near-misses × 4 + harsh brakes × 1 (+ turns, accelerations), per 1,000 vehicle-km of exposure. Fog season (Dec–Jan) and monsoon (Jun–Sep) are visible.</p>`;
  }
  function renderEvidence() {
    if (!EVD) { $("#tab-evidence").innerHTML = "<p>Evidence data not bundled.</p>"; return; }
    const E = EVD, m = (o, d = 1) => `${fmt(o.mean, d)} <span class="note">± ${fmt(o.sd, d)}</span>`;
    const row = (t, k, d = 1) => `<tr><td>${t}</td><td>${m(E.holdout.faithful[k], d)}</td><td>${m(E.holdout.noisy[k], d)}</td><td>${m(E.development.faithful[k], d)}</td><td>${m(E.development.noisy[k], d)}</td></tr>`;
    $("#tab-evidence").innerHTML = `<div class="kpis"><div class="kpi"><b>−${fmt(E.holdout.faithful.policy_cut.mean, 1)}%</b><span>simulated expected-crash risk for +${fmt(E.holdout.faithful.policy_time.mean, 1)}% fleet driving time (default policy, holdout)</span></div>
      <div class="kpi"><b>+${fmt(E.holdout.faithful.blend_minus_road.mean, 1)} pts</b><span>over the strongest simple baseline (road features only) at +2% time; ${E.holdout.faithful.blend_minus_road.losses} of 5 worlds lost</span></div>
      <div class="kpi"><b>${fmt(E.holdout.faithful.safer.mean, 0)}%</b><span>of switches had lower simulated true risk</span></div>
      <div class="kpi"><b>${PAR ? PAR.decisions_agree + "/" + PAR.trips : "–"}</b><span>archived reference trips: browser matched Python decisions and chosen routes</span></div></div>
      <div class="panel"><h3>Simulated evaluation (mean ± sd over 5 network realisations per setting)</h3><div class="tablewrap"><table>
      <tr><th>Measure</th><th>Holdout · faithful proxy</th><th>Holdout · noisy proxy</th><th>Development · faithful</th><th>Development · noisy</th></tr>
      ${row("Risk cut at +2% time: RakshaMarg blend (deployed)", "mb2_blend")}${row("Risk cut at +2% time: RakshaMarg model", "mb2_model")}${row("Risk cut at +2% time: road features only", "mb2_road")}
      ${row("Risk cut at +2% time: braking per veh-km", "mb2_braking")}${row("Risk cut at +2% time: crash history", "mb2_crash")}
      ${row("Segment ranking: model (Spearman)", "seg_model", 3)}${row("Segment ranking: deployed blend", "seg_blend", 3)}${row("Segment ranking: braking per veh-km", "seg_braking", 3)}
      ${row("Default policy: expected-crash reduction %", "policy_cut")}${row("Default policy: extra fleet time %", "policy_time", 2)}${row("Switches with lower true risk %", "safer")}${row("90% band coverage %", "coverage")}
      </table></div><p class="note">“+2% time” values are interpolated from per-trip budget sweeps (analysis curve, not an online allocator). Faithful and noisy runs share the same 5 base networks, so there are 5 independent network realisations per suite, not 10. Review cases (holdout): ${E.holdout.deferral.defers} of ${E.holdout.deferral.trips} trips; ${fmt(E.holdout.deferral.deferred_alternatives_truly_safer_pct, 0)}% of the alternatives under review were in fact lower-risk, so the evidence gate is conservative. Decision-object consistency: 0 inconsistencies in ${(E.holdout.integrity.decisions_checked + E.development.integrity.decisions_checked).toLocaleString()} simulated method–trip evaluations (a consistency check, not a safety or legality guarantee).
      All numbers are simulated: they test the method against a known ground truth, not on-road crash reductions.</p>
      <div class="banner"><b>Evaluated policy vs product behaviour.</b> The simulation scores review cases as if the trip kept the fastest route (fallback) and adds no supervisor waiting time. In the product those trips wait for a supervisor's choice. Review affected ${fmt(100 * E.review_cost.review_share, 1)}% of holdout trips (1.3–11.3% by world); with a ${fmt(E.review_cost.mean_trip_min, 0)}-minute average trip, every 10 minutes of supervisor wait adds about ${fmt(E.review_cost.wait_cost_pct["10"], 1)} percentage points of fleet driving time, on top of the routing cost above. Supervisor choices could move the risk figures either way; this is not yet evaluated.</div></div>`;
  }
  function renderHow() {
    $("#tab-how").innerHTML = `<div class="panel prose"><h2 style="margin-top:0">How RakshaMarg decides</h2>
      <ol><li><b>Exposure-normalised risk.</b> Fleet events (harsh braking, near-misses, crashes) are divided by vehicle-km, so busy roads do not look falsely dangerous.</li>
      <li><b>Learned risk per segment, time and weather.</b> A Poisson GLM × gradient-boosting model learns from near-misses + crashes, then Empirical Bayes corrects each road with its own crash history. For dispatch it is blended geometrically with a transparent braking rate.</li>
      <li><b>Restriction-aware candidates.</b> k fastest routes plus risk-penalised routes, excluding configured no-entry streets and active zones. If none exists, the card says whether restrictions or the network itself are the cause.</li>
      <li><b>Evidence gate.</b> Paired model uncertainty draws compare each qualifying alternative with the fastest route. Below the fleet's threshold, the trip is held for a supervisor, whose choice is recorded.</li>
      <li><b>Close the loop.</b> Assigned trips are logged with route and risk; post-trip outcomes raise monitoring flags.</li></ol>
      <h2>What is real, what is simulated, what is not yet modelled</h2><ul>
      <li><b>Simulated fleet region:</b> the full trained engine on a synthetic Indian fleet region with known ground truth (real fleet crash data is not public). Browser decisions match the archived Python reference on 300/300 trips.</li>
      <li><b>Real roads (experimental):</b> live OpenStreetMap geometry and Open-Meteo weather. One-way, roundabout and heavy-vehicle access tags are applied; endpoints snap to the connected network. Risk scores are relative and simulator-trained, not calibrated crash estimates.</li>
      <li><b>Not modelled yet:</b> turn restrictions, conditional access, weight/height limits (flagged for verification), live traffic speeds, and per-segment arrival-time weather. Restriction windows are checked along the route's estimated arrival times.</li>
      <li><b>Model-based probability:</b> the share of paired uncertainty draws in which the alternative has lower expected risk. It is not the probability of avoiding a crash, and it is not calibrated on real data.</li></ul>
      <h2>Release integrity</h2><p>Model/evaluation fingerprint <code>${MODEL}</code>. Dispatch scorer: ${esc(D.meta.dispatch_scorer)}. Archived parity: ${PAR ? `${PAR.candidate_sets_identical}/${PAR.trips} identical candidate sets; ${PAR.decisions_agree}/${PAR.trips} identical decisions and fastest/considered/chosen routes` : "see tests"}.</p></div>`;
  }

  const LK = window.RM_LINKS || {}, linkHtml = [["demo_url", "Live demo"], ["repo_url", "Source code"], ["video_url", "Demo video"]].filter(([k]) => LK[k]).map(([k, t]) => `<a href="${esc(LK[k])}" target="_blank" rel="noopener">${t}</a>`).join(" · ");
  $("#foot").innerHTML = (linkHtml ? linkHtml + " · " : "") + `RakshaMarg prototype v${VERSION} · Team PLACER · Shantanu Singh · IIT (BHU) Varanasi · Netradyne Campus Innovation Challenge 2026 · model <code>${MODEL}</code> · Map data © OpenStreetMap contributors (ODbL) · Weather: Open-Meteo (CC BY 4.0)`;
  renderControls(); loadExample(EX.typical_switch ? "typical_switch" : Object.keys(EX)[0]);
  window.RM_APP = { S, runSim, runReal, loadExample, setMode, loadRoads, presetReal, getLog };
})();
