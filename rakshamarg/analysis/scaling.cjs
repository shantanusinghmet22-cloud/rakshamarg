// Supplementary: decision latency of the browser/Node engine vs road-network size (theme task 8).
const RM = require("../web/engine.js"), fs = require("fs");
const out = [];
for (const n of [12, 24, 48, 96]) {                       // n x n grid: about 2n^2 segments
  const nodes = [], edges = [], rng = RM.mulberry32(n);
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) nodes.push({ id: `${i},${j}`, x: i * 2, y: j * 2 });
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) for (const [di, dj] of [[1, 0], [0, 1]]) if (i + di < n && j + dj < n) {
    const len = 2 * (1 + 0.2 * rng()); edges.push({ id: edges.length, u: `${i},${j}`, v: `${i + di},${j + dj}`, len, time: len / (30 + 40 * rng()) * 60 }); }
  const g = RM.makeGraph(nodes, edges), rate = edges.map(() => 1e-6 * Math.exp(rng() * 2));
  const sd = edges.map(() => 0.4), cls = edges.map((e, i) => i % 4), t0 = Date.now();
  const mult = RM.multiplierDraws(edges.length, sd, cls, 4, 0.1, 200, 1); const drawMs = Date.now() - t0;
  const lat = [];
  for (let k = 0; k < 25; k++) { const a = `${Math.floor(rng() * n / 4)},${Math.floor(rng() * n)}`, b = `${n - 1 - Math.floor(rng() * n / 4)},${Math.floor(rng() * n)}`;
    const s = process.hrtime.bigint(); RM.decideOn(g, a, b, rate, mult, 1, "day", { maxExtra: 12, minCut: 15, pReq: 0.9 }, new Set());
    lat.push(Number(process.hrtime.bigint() - s) / 1e6); }
  lat.sort((x, y) => x - y);
  out.push({ segments: edges.length, p50_ms: +lat[12].toFixed(1), p95_ms: +lat[23].toFixed(1), context_setup_ms: drawMs, heap_mb: +(process.memoryUsage().heapUsed / 1e6).toFixed(0) });
}
fs.writeFileSync("outputs/supplementary/scaling_engine.json", JSON.stringify(out, null, 1)); console.table(out);
