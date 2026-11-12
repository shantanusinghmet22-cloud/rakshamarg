"""figures.py - plots and the offline dispatcher demo page (all from SIMULATED data)."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullLocator

INK, MUTED, GRID = "#1B2430", "#6B7686", "#D5DAE1"
GREEN, AMBER, RED, BLUE = "#1F9D63", "#F2A900", "#D64545", "#2C6E9B"
CMAP = LinearSegmentedColormap.from_list("risk", [GREEN, AMBER, RED])
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": GRID, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED})
LABELS = {"NH corridor": (1.0, 15.0), "Urban core": (2.2, 2.6), "Ghat section": (33.0, 27.2), "SH": (20.6, 26.6)}


def _net(ax, E, vals=None, norm=None, lw=1.0, alpha=1.0):
    segs = [[(r.x1, r.y1), (r.x2, r.y2)] for r in E.itertuples()]
    widths = E.cls.map({"NH": 3.4, "SH": 2.6, "GHAT": 2.2, "URBAN": 1.6, "MDR": 1.4}).values * lw
    lc = LineCollection(segs, linewidths=widths, alpha=alpha, capstyle="round",
                        **({"colors": GRID} if vals is None else {"cmap": CMAP, "norm": norm}))
    if vals is not None:
        lc.set_array(vals)
    ax.add_collection(lc)
    ax.set_xlim(E[["x1", "x2"]].values.min() - 1, E[["x1", "x2"]].values.max() + 1)
    ax.set_ylim(E[["y1", "y2"]].values.min() - 1, E[["y1", "y2"]].values.max() + 1)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    return lc


def _labels(ax, fs=10):
    for t, (x, y) in LABELS.items():
        ax.text(x, y, t, fontsize=fs, color=INK, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=GRID, alpha=0.9))


def _path(ax, E, eids, color, lw, z):
    for e in eids:
        r = E.loc[e]
        ax.plot([r.x1, r.x2], [r.y1, r.y2], color=color, lw=lw, solid_capstyle="round", zorder=z)


def make_figures(OUT, E, G, model, hs, cases, heat=None):
    # heat-map
    nr = model.edge_rates("night", "clear").rate.values * 1e6
    lo, hi = np.quantile(nr, 0.03), np.quantile(nr, 0.99)
    fig, ax = plt.subplots(figsize=(11, 7), dpi=200)
    lc = _net(ax, E, nr, LogNorm(lo, hi))
    for r in hs.head(8).itertuples():
        ax.scatter(r.x_km, r.y_km, s=520, facecolor="none", edgecolor=INK, linewidth=1.6, zorder=5)
        ax.text(r.x_km, r.y_km, str(r.rank), ha="center", va="center", fontsize=9, fontweight="bold", color=INK, zorder=6)
    _labels(ax)
    cb = fig.colorbar(lc, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("Predicted crash rate, night (per million veh-km)", color=INK); cb.outline.set_visible(False)
    tks = [t for t in (10, 20, 50, 100, 200, 500, 1000) if lo <= t <= hi]
    cb.ax.yaxis.set_major_locator(FixedLocator(tks)); cb.ax.yaxis.set_minor_locator(NullLocator())
    cb.ax.set_yticklabels([str(t) for t in tks])
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_risk_map.png", bbox_inches="tight"); plt.close(fig)

    # selected route comparison
    sel = cases["selected_switch"]
    fig, ax = plt.subplots(figsize=(11, 7), dpi=200)
    if heat is not None:                         # T5: risk heat-map overlay under the route map
        hv = heat[sel["context"]] * 1e6
        _net(ax, E, hv, LogNorm(np.quantile(hv, 0.03), np.quantile(hv, 0.99)), lw=0.9, alpha=0.45)
    else:
        _net(ax, E, alpha=0.9)
    _path(ax, E, sel["fastest"]["eids"], RED, 6, 3)
    _path(ax, E, sel["chosen"]["eids"], GREEN, 6, 4)
    for w in sel["reasons_fastest"]:
        r = E.loc[w["edge_id"]]
        ax.scatter((r.x1 + r.x2) / 2, (r.y1 + r.y2) / 2, marker="^", s=260, color=AMBER, edgecolor=INK, zorder=6)
    on, dn = G.nodes[tuple(sel["origin"])], G.nodes[tuple(sel["destination"])]
    ax.scatter([on["x"], dn["x"]], [on["y"], dn["y"]], s=180, color=INK, zorder=7)
    ax.text(on["x"] - 0.4, on["y"] + 1.0, "Depot", fontsize=11, fontweight="bold", color=INK)
    ax.text(dn["x"] - 2.5, dn["y"] + 1.0, "Customer", fontsize=11, fontweight="bold", color=INK)
    _labels(ax)
    ax.legend(handles=[Line2D([0], [0], color=RED, lw=5, label=f"Fastest: {sel['fastest']['time_min']:.0f} min, risk index {sel['fastest']['risk_index']}"),
                       Line2D([0], [0], color=GREEN, lw=5, label=f"Recommended: {sel['chosen']['time_min']:.0f} min, risk index {sel['chosen']['risk_index']}"),
                       Line2D([0], [0], marker="^", color="w", markerfacecolor=AMBER, markeredgecolor=INK, markersize=13, label="Top risk segments on fastest route"),
                       Line2D([0], [0], color=AMBER, lw=3, alpha=0.5, label="Background: segment risk heat-map (green low, red high)")],
              loc="lower right", frameon=True, fontsize=10)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_route_compare.png", bbox_inches="tight"); plt.close(fig)

    # three typical outcomes
    keys = [k for k in ("typical_switch", "typical_keep", "typical_defer") if k in cases]
    fig, axs = plt.subplots(1, len(keys), figsize=(5.2 * len(keys), 4.6), dpi=200)
    ttl = {"switch": ("SWITCH", GREEN), "keep": ("KEEP FASTEST", INK), "defer": ("DEFER TO SUPERVISOR", "#B07A00")}
    for ax, k in zip(np.atleast_1d(axs), keys):
        c = cases[k]
        _net(ax, E, lw=0.6, alpha=0.8)
        if c["decision"] == "switch":
            _path(ax, E, c["chosen"]["eids"], GREEN, 5, 3)
        elif c["decision"] == "defer" and c["considered"]:
            _path(ax, E, c["considered"]["eids"], AMBER, 5, 3)
        for e in c["fastest"]["eids"]:
            r = E.loc[e]
            ax.plot([r.x1, r.x2], [r.y1, r.y2], color=RED if c["decision"] == "switch" else INK, lw=2.2, ls=(0, (2, 1.5)) if c["decision"] != "keep" else "-", zorder=4)
        on, dn = G.nodes[tuple(c["origin"])], G.nodes[tuple(c["destination"])]
        ax.scatter([on["x"], dn["x"]], [on["y"], dn["y"]], s=60, color=INK, zorder=7)
        t, col = ttl[c["decision"]]
        ax.set_title(t, color=col, fontsize=14, fontweight="bold", loc="left")
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_three_outcomes.png", bbox_inches="tight"); plt.close(fig)

    # pareto for selected
    opts = sel["options"]
    tt = np.array([o["time_min"] for o in opts]); rr = np.array([o["risk_index"] for o in opts]); ip = np.array([o["pareto"] for o in opts])
    f_, c_ = sel["fastest"], sel["chosen"]
    fig, ax = plt.subplots(figsize=(7.5, 5), dpi=200)
    if (~ip).any():
        ax.scatter(tt[~ip], rr[~ip], s=70, color=GRID, edgecolor=MUTED, label="Dominated candidate", zorder=3)
    o_ = np.argsort(tt[ip]); ax.plot(tt[ip][o_], rr[ip][o_], color=MUTED, lw=1.5, ls="--", zorder=2)
    ax.scatter(tt[ip], rr[ip], s=90, color=AMBER, edgecolor=INK, label="Pareto-optimal option", zorder=4)
    ax.scatter([f_["time_min"]], [f_["risk_index"]], s=220, color=RED, edgecolor=INK, zorder=5, label="Fastest")
    ax.scatter([c_["time_min"]], [c_["risk_index"]], s=220, color=GREEN, edgecolor=INK, zorder=5, label="Recommended")
    ax.axvline(f_["time_min"] * 1.12, color=MUTED, lw=1, ls=":")
    ax.text(f_["time_min"] * 1.12 + 0.3, rr.max() - 2, "fleet policy:\n<=12% extra time", fontsize=9, color=MUTED, va="top")
    ax.annotate(f"P(truly safer) = {sel['p_safer']:.3f}\n+{sel['extra_min']:.0f} min", xy=(c_["time_min"], c_["risk_index"]),
                xytext=(c_["time_min"] + 2.5, c_["risk_index"] + 14), fontsize=11, fontweight="bold", color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.5))
    ax.set_xlabel("Travel time (min)"); ax.set_ylabel("Risk index (0-100)")
    ax.grid(color=GRID, lw=0.6); ax.legend(fontsize=9, frameon=True, loc="lower left")
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_pareto.png", bbox_inches="tight"); plt.close(fig)


def make_demo_html(OUT, E, G, cases, heat=None):
    """Offline, single-file dispatcher demo: open in any browser, no server needed."""
    x0, x1 = E[["x1", "x2"]].values.min() - 1, E[["x1", "x2"]].values.max() + 1
    y0, y1 = E[["y1", "y2"]].values.min() - 1, E[["y1", "y2"]].values.max() + 1
    sx = lambda x: (x - x0) / (x1 - x0) * 640
    sy = lambda y: (y1 - y) / (y1 - y0) * 400
    def lines(eids, color, w, cls=""):
        return "".join(f'<line x1="{sx(E.loc[e].x1):.1f}" y1="{sy(E.loc[e].y1):.1f}" x2="{sx(E.loc[e].x2):.1f}" y2="{sy(E.loc[e].y2):.1f}" '
                       f'stroke="{color}" stroke-width="{w}" stroke-linecap="round" class="{cls}"/>' for e in eids)
    base = lines(E.edge_id, "var(--grid)", 1.2)
    def heat_lines(ctx):                         # T5: heat-map overlay for the trip's own departure context
        if heat is None:
            return base
        v = np.log(heat[ctx]); q = np.clip((v - np.quantile(v, 0.05)) / (np.quantile(v, 0.99) - np.quantile(v, 0.05)), 0, 1)
        col = lambda t: "#%02x%02x%02x" % tuple(int(a + (b - a) * t) for a, b in ((31, 214), (157, 69), (99, 69)))
        return "".join(f'<line x1="{sx(E.loc[e].x1):.1f}" y1="{sy(E.loc[e].y1):.1f}" x2="{sx(E.loc[e].x2):.1f}" y2="{sy(E.loc[e].y2):.1f}" '
                       f'stroke="{col(q[e])}" stroke-opacity="0.45" stroke-width="2" stroke-linecap="round"/>' for e in E.edge_id)
    tabs, panes = [], []
    msg = {"switch": ("SWITCH", "var(--green)", "Evidence is strong enough: assign the safer route."),
           "keep": ("KEEP FASTEST", "var(--ink2)", "No alternative clears the fleet policy (>=15% lower risk for <=12% extra time)."),
           "defer": ("DEFER TO SUPERVISOR", "var(--amber)", "An alternative looks safer, but the evidence is too weak (P < 0.90). Keep fastest, flag for review.")}
    order = [k for k in ("selected_switch", "typical_switch", "typical_keep", "typical_defer") if k in cases]
    for i, k in enumerate(order):
        c = cases[k]
        head, col, expl = msg[c["decision"]]
        svg = heat_lines(c["context"]) + (lines(c["considered"]["eids"], "var(--green)" if c["decision"] == "switch" else "var(--amber)", 5) if c["considered"] else "")
        svg += lines(c["fastest"]["eids"], "var(--red)" if c["decision"] == "switch" else "var(--ink)", 5)
        on, dn = G.nodes[tuple(c["origin"])], G.nodes[tuple(c["destination"])]
        svg += f'<circle cx="{sx(on["x"]):.1f}" cy="{sy(on["y"]):.1f}" r="7" fill="var(--ink)"/><circle cx="{sx(dn["x"]):.1f}" cy="{sy(dn["y"]):.1f}" r="7" fill="var(--ink)"/>'
        def row(lab, s, colr):
            return (f'<div class="opt" style="border-color:{colr}"><div><b style="color:{colr}">{lab}</b><br>'
                    f'<span>{s["time_min"]:.0f} min · {s["km"]:.0f} km · {s["confidence"]} confidence</span><br>'
                    f'<span>90% band: {s["band90"][0]}–{s["band90"][1]} per 1,000 trips</span></div>'
                    f'<div class="ri" style="color:{colr}">{s["risk_index"]}<small>risk index</small></div></div>')
        rows = row("Fastest", c["fastest"], "var(--red)")
        if c["considered"]:
            rows += row({"switch": "Recommended", "defer": "Alternative (evidence too weak)", "keep": "Best alternative (fails policy)"}[c["decision"]],
                        c["considered"], "var(--green)" if c["decision"] == "switch" else "var(--amber)")
        reasons = "".join(f"<li>{'; '.join(w['reasons'])}</li>" for w in c["reasons_fastest"])
        p = f"P(alternative truly safer) = {c['p_safer']:.3f}" if c["p_safer"] is not None else "No qualifying alternative"
        title = {"selected_switch": "Selected example", "typical_switch": "Typical switch", "typical_keep": "Typical keep", "typical_defer": "Typical defer"}[k]
        tabs.append(f'<button class="tab{" on" if i == 0 else ""}" onclick="show({i})">{title}</button>')
        panes.append(f'''<section class="pane" id="p{i}" style="display:{'grid' if i == 0 else 'none'}">
<div class="map"><svg viewBox="0 0 640 400" role="img" aria-label="Route map">{svg}</svg>
<p class="cap">Trip {tuple(c["origin"])} → {tuple(c["destination"])} · departure {c["context"].replace("/", ", ")}</p></div>
<div class="card"><div class="dec" style="background:{col}">{head}</div><p>{expl}</p><p class="p">{p}</p>{rows}
<h4>Why the fastest route carries risk</h4><ul>{reasons}</ul>
<p class="note">Ground truth (simulation only): fastest {c["fastest"]["true_per_1000"]}, chosen {c["chosen"]["true_per_1000"]} crashes per 1,000 trips.</p></div></section>''')
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RakshaMarg dispatcher demo (simulated data)</title><style>
:root{{--bg:#fff;--surf:#F1F4F7;--ink:#1B2430;--ink2:#4A5566;--grid:#D5DAE1;--green:#1F9D63;--amber:#B07A00;--red:#D64545;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0F161F;--surf:#1B2430;--ink:#F1F4F7;--ink2:#AAB3C0;--grid:#3A4656;--green:#34C27F;--amber:#F2A900;--red:#F06A6A;color-scheme:dark}}}}
body{{margin:0;font-family:Calibri,Carlito,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink)}}
header{{padding:18px 24px}}h1{{margin:0;font-size:22px}}header p{{margin:4px 0 0;color:var(--ink2)}}
.tabs{{display:flex;gap:8px;padding:0 24px;flex-wrap:wrap}}.tab{{border:1px solid var(--grid);background:var(--surf);color:var(--ink);padding:8px 14px;border-radius:18px;cursor:pointer;font-size:14px}}
.tab.on{{background:var(--ink);color:var(--bg)}}.pane{{grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:20px;padding:18px 24px}}
@media (max-width:860px){{.pane{{grid-template-columns:1fr}}}}svg{{width:100%;height:auto;background:var(--surf);border-radius:10px}}
.cap,.note{{color:var(--ink2);font-size:13px}}.card{{background:var(--surf);border-radius:12px;padding:16px}}
.dec{{color:#fff;font-weight:700;padding:6px 12px;border-radius:14px;display:inline-block}}.p{{font-weight:700}}
.opt{{display:flex;justify-content:space-between;border:2px solid;border-radius:10px;padding:10px;margin:8px 0;background:var(--bg);font-size:14px}}
.opt span{{color:var(--ink2);font-size:13px}}.ri{{font-size:30px;font-weight:700;text-align:right}}.ri small{{display:block;font-size:11px;font-weight:400;color:var(--ink2)}}
h4{{margin:14px 0 4px}}ul{{margin:0;padding-left:18px;font-size:14px}}</style></head><body>
<header><h1>RakshaMarg · dispatcher demo</h1><p>Generated by run_demo.py from a <b>simulated</b> fleet region. Not real roads or real crash outcomes.
Background colour = segment risk heat-map for the trip's departure context (green low, red high).</p></header>
<nav class="tabs">{"".join(tabs)}</nav>{"".join(panes)}
<script>function show(i){{document.querySelectorAll('.pane').forEach((p,j)=>p.style.display=j===i?'grid':'none');
document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('on',j===i));}}</script></body></html>'''
    open(f"{OUT}/dispatcher_demo.html", "w").write(html)
