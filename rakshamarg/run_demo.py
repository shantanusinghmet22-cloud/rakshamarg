"""
run_demo.py - end-to-end RakshaMarg proof of concept on a simulated Indian fleet region.

    python run_demo.py                       # primary run (seed 7): metrics, figures, demo, model artifacts
    python run_demo.py --seed 11 --out outputs/seeds/seed_11 --no-figures
    python summarize_seeds.py                # robustness across simulated worlds

IMPORTANT: every number produced here is measured on SIMULATED data with known ground truth.
It validates the method, not real-world crash reductions (see README section 4).
"""
import argparse, hashlib, json, os, pickle, time, warnings, glob as _glob
import numpy as np
import pandas as pd
import networkx as nx
from scipy import stats

from rakshamarg.world import simulate, context_multiplier, CONFIG, TIME_BUCKETS, WEATHERS
from rakshamarg import pipeline as P

warnings.filterwarnings("ignore")
ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--out", default="outputs")
ap.add_argument("--no-figures", action="store_true")
ap.add_argument("--fidelity", default="faithful", choices=["faithful", "noisy"])
args = ap.parse_args()
OUT = args.out
os.makedirs(OUT, exist_ok=True)
SRC = sorted(_glob.glob("rakshamarg/*.py")) + ["run_demo.py", "figures.py"]
SHA = hashlib.sha256(b"".join(open(f, "rb").read() for f in SRC)).hexdigest()[:12]
DISPATCH = "RakshaMarg + braking blend"
M = {"seed": args.seed, "surrogate_fidelity": args.fidelity, "data": "SIMULATED region with known ground truth",
     "source_sha256_12": SHA, "dispatch_scorer": DISPATCH + " (geometric: model rate x sqrt(braking rate / model mean rate))"}
t0 = time.time()

# ------------------------------------------------------------------ simulate world
W = simulate(seed=args.seed, fidelity=args.fidelity)
G, E, cells, raw = W["G"], W["edges"], W["cells"], W["events"]
base = CONFIG["base_crash_rate"]
M["world"] = dict(segments=int(len(E)), network_km=round(float(E.length_km.sum()), 1),
                  veh_km=round(float(cells.exposure_vkm.sum()), 0), raw_events=int(len(raw)),
                  crashes=int(cells.n_crash.sum()), near_misses=int(cells.n_near_miss.sum()),
                  harsh_brakes=int(cells.n_harsh_brake.sum()),
                  hidden_hazard_segments=int((E.hidden_mult > 1).sum()),
                  public_blackspot_segments=int(E.public_blackspot.sum()),
                  truck_no_entry_segments=int(E.truck_no_entry_day.sum()))

# ------------------------------------------------------------------ T1 preprocess
t = time.time()
ev, log = P.preprocess(raw, E)
log["events_per_second"] = int(log["raw_rows"] / max(time.time() - t, 1e-6))
M["preprocess"] = log
asof = pd.Timestamp(f"{CONFIG['year']}-10-01")
ev_tr = ev[ev.timestamp < asof]
c_tr, c_te = cells[cells.month <= 9], cells[cells.month >= 10]

# ------------------------------------------------------------------ T2 hotspots
hs, _ = P.detect_hotspots(ev_tr, E, c_tr, asof)
hid = E[E.hidden_mult > 1]
hs["near_hidden_hazard"] = [bool(np.hypot((hid.x1 + hid.x2) / 2 - r.x_km, (hid.y1 + hid.y2) / 2 - r.y_km).min() < 1.2)
                            for r in hs.itertuples()]
top10 = hs.head(10)
M["hotspots"] = dict(n=int(len(hs)), top10_on_public_list=int(top10.public_blackspot.sum()),
                     top10_hidden_hazard_not_on_public_list=int((top10.near_hidden_hazard & (top10.public_blackspot == 0)).sum()))
hs.drop(columns=["near_hidden_hazard"]).round(3).to_csv(f"{OUT}/hotspots.csv", index=False)

# ------------------------------------------------------------------ T3 model: tune k + measure dispersion on validation
asof_v = pd.Timestamp(f"{CONFIG['year']}-07-01")
val = c_tr[(c_tr.month >= 7) & (c_tr.exposure_vkm > 0)]
ev_v = ev_tr[ev_tr.timestamp < asof_v]
def pois_dev(y, mu):
    mu = np.clip(mu, 1e-12, None)
    return float(2 * np.sum(np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0) - (y - mu)))
tune, tuned = {}, {}
for k in (1, 2, 4, 8, 16, 32):
    m = P.RiskModel(k=k).fit(c_tr[c_tr.month <= 6], ev_v, E, asof_v)
    tune[k] = pois_dev(val.n_crash.values, m.predict_cells(val) * val.exposure_vkm.values)
    tuned[k] = m
k_best = min(tune, key=tune.get)
phi = tuned[k_best].estimate_dispersion(val)          # measured on observable validation crashes
# dispersion of the DEPLOYED blend scorer, built only from months <= 6 and measured on months 7-9
_c6 = c_tr[c_tr.month <= 6]
_e6 = _c6.groupby("edge_id")[["n_crash", "n_harsh_brake", "exposure_vkm"]].sum().reindex(E.edge_id).fillna(0)
_hb6 = (_e6.n_harsh_brake + _e6.n_harsh_brake.sum() / _e6.exposure_vkm.sum() * 5000) / (_e6.exposure_vkm + 5000)
_hb6 = (_hb6 * _c6.n_crash.sum() / np.sum(_hb6.values[_c6.edge_id] * _c6.exposure_vkm)).values
_t6 = _c6[_c6.exposure_vkm > 0]
_rm6 = (pd.Series(tuned[k_best].predict_cells(_t6) * _t6.exposure_vkm.values).groupby(_t6.edge_id.values).sum()
        / _t6.groupby("edge_id").exposure_vkm.sum()).reindex(E.edge_id)
_rm6 = _rm6.fillna(pd.Series(tuned[k_best].edge_rates("day", "clear").rate.values, index=E.edge_id)).values
phi_blend = P.dispersion_from_rates(val, tuned[k_best].predict_cells(val) * np.sqrt(_hb6 / _rm6)[val.edge_id.values])
M["dispersion_phi_blend_by_time"] = {k: round(v, 3) for k, v in phi_blend.items()}
M["eb_k"], M["dispersion_phi_by_time"] = k_best, {k: round(v, 3) for k, v in phi.items()}

model = P.RiskModel(k=k_best, n_boot=6).fit(c_tr, ev_tr, E, asof); model.phi = phi
geo = P.RiskModel(use_telematics=False, use_eb=False).fit(c_tr, ev_tr, E, asof)
tel_noeb = P.RiskModel(k=k_best, use_eb=False).fit(c_tr, ev_tr, E, asof)
geo_eb = P.RiskModel(k=k_best, use_telematics=False).fit(c_tr, ev_tr, E, asof)
crash_t = P.RiskModel(k=k_best, target="crash").fit(c_tr, ev_tr, E, asof)
gbm_only = P.RiskModel(k=k_best, use_glm=False).fit(c_tr, ev_tr, E, asof)

# ------------------------------------------------------------------ T8 segment-level evaluation (held-out Oct-Dec)
te = c_te[c_te.exposure_vkm > 0].copy()
glob = c_tr.n_crash.sum() / c_tr.exposure_vkm.sum()
etr = c_tr.groupby("edge_id")[["n_crash", "n_harsh_brake", "n_near_miss", "exposure_vkm"]].sum().reindex(E.edge_id).fillna(0)
hist_rate = ((etr.n_crash + glob * 2000) / (etr.exposure_vkm + 2000)).values
hb_km = (etr.n_harsh_brake / E.length_km.values).values                       # naive: per road km
hb_km_scale = c_tr.n_crash.sum() / np.sum(hb_km[c_tr.edge_id] * c_tr.exposure_vkm)
g_hb = etr.n_harsh_brake.sum() / etr.exposure_vkm.sum()
hb_vkm = ((etr.n_harsh_brake + g_hb * 5000) / (etr.exposure_vkm + 5000)).values   # reviewer's stronger baseline
hb_vkm_scale = c_tr.n_crash.sum() / np.sum(hb_vkm[c_tr.edge_id] * c_tr.exposure_vkm)

const = lambda arr: (lambda df: arr[df.edge_id.values])
# Blend: context effects from RakshaMarg, per-road level 50/50 with the transparent braking rate (fixed a priori)
trp = c_tr[c_tr.exposure_vkm > 0]
rm_cnt = pd.Series(model.predict_cells(trp) * trp.exposure_vkm.values).groupby(trp.edge_id.values).sum()
rm_avg = (rm_cnt / trp.groupby("edge_id").exposure_vkm.sum()).reindex(E.edge_id)
rm_avg = rm_avg.fillna(pd.Series(model.edge_rates("day", "clear").rate.values, index=E.edge_id)).values
hb_s = hb_vkm * hb_vkm_scale
blend_w = np.sqrt(hb_s / rm_avg)
blend_cells = lambda df: model.predict_cells(df) * blend_w[df.edge_id.values]
methods = {
    "Harsh brakes per road-km (naive)": const(hb_km * hb_km_scale),
    "Crash history (smoothed rate)": const(hist_rate),
    "Harsh brakes per veh-km (smoothed)": const(hb_vkm * hb_vkm_scale),
    "Road features only": geo.predict_cells,
    "Road features + EB": geo_eb.predict_cells,
    "Road + telematics, no EB": tel_noeb.predict_cells,
    "RakshaMarg, crash-only target": crash_t.predict_cells,
    "RakshaMarg, trees only (no GLM base)": gbm_only.predict_cells,
    "RakshaMarg (full)": model.predict_cells,
    "RakshaMarg + braking blend": blend_cells,
    "Oracle (true risk)": lambda df: df.true_crash_rate.values,
}
true_rate_ctx = lambda tb, w: base * E.true_rel_risk.values * context_multiplier(E, tb, w)
grid = pd.DataFrame([(e, tb, w) for tb in TIME_BUCKETS for w in WEATHERS for e in E.edge_id],
                    columns=["edge_id", "tb", "weather"])
grid["true_crash_rate"] = np.concatenate([true_rate_ctx(tb, w) for tb in TIME_BUCKETS for w in WEATHERS])
dc = grid[(grid.tb == "day") & (grid.weather == "clear")]
y = te.n_crash.values
null_dev = pois_dev(y, np.full(len(y), y.sum() / te.exposure_vkm.sum()) * te.exposure_vkm.values)
expo_te_edge = te.groupby("edge_id").exposure_vkm.sum().reindex(E.edge_id).fillna(0).values
sparse = etr.exposure_vkm.values < np.quantile(etr.exposure_vkm.values[etr.exposure_vkm.values > 0], 0.25)
true_cnt = te.assign(tc=te.true_crash_rate * te.exposure_vkm).groupby("edge_id").tc.sum().reindex(E.edge_id).fillna(0).values
seg_eval = {}
for name, fn in methods.items():
    mu = fn(te) * te.exposure_vkm.values
    pred_cnt = pd.Series(mu).groupby(te.edge_id.values).sum().reindex(E.edge_id).fillna(0).values
    rate_e = np.where(expo_te_edge > 0, pred_cnt / np.maximum(expo_te_edge, 1e-9), 0)
    dcr = fn(dc)
    used = expo_te_edge > 0
    idx = np.where(used)[0][np.argsort(-rate_e[used])]
    top = idx[np.cumsum(expo_te_edge[idx]) / expo_te_edge[used].sum() <= 0.10]
    lift = (true_cnt[top].sum() / expo_te_edge[top].sum()) / (true_cnt[used].sum() / expo_te_edge[used].sum())
    seg_eval[name] = dict(
        spearman_segments=round(float(stats.spearmanr(dcr, dc.true_crash_rate).correlation), 3),
        spearman_sparse_segments=round(float(stats.spearmanr(dcr[sparse], dc.true_crash_rate.values[sparse]).correlation), 3),
        spearman_segment_x_context=round(float(stats.spearmanr(fn(grid), grid.true_crash_rate).correlation), 3),
        top10pct_lift=round(float(lift), 2),
        deviance_explained_pct=round(100 * (1 - pois_dev(y, mu) / null_dev), 1))
M["evaluation_segments"] = seg_eval
M["test_period"] = dict(months="Oct-Dec (held out)", crashes=int(y.sum()), veh_km=round(float(te.exposure_vkm.sum())))

mu = model.predict_cells(te) * te.exposure_vkm.values
q = pd.qcut(pd.Series(mu / te.exposure_vkm.values).rank(method="first"), 5, labels=False)
cal = pd.DataFrame({"q": q, "pred": mu, "obs": y}).groupby("q").sum()
M["calibration_quintiles"] = dict(predicted=cal.pred.round(1).tolist(), observed=cal.obs.astype(int).tolist())

# ------------------------------------------------------------------ T4 route-level: policy, deferral, matched budgets, coverage
rng = np.random.default_rng(1000 + args.seed)
nodes = list(G.nodes)
contexts = [("day", "clear"), ("night", "clear"), ("night", "fog"), ("evening", "rain")]
rate_src = {
    "RakshaMarg": {c: model.edge_rates(*c) for c in contexts},
    "Harsh brakes per veh-km": {c: pd.DataFrame({"edge_id": E.edge_id, "rate": hb_vkm * hb_vkm_scale}) for c in contexts},
    "Crash history": {c: pd.DataFrame({"edge_id": E.edge_id, "rate": hist_rate}) for c in contexts},
    "Road features only": {c: geo.edge_rates(*c) for c in contexts},
}
rate_src[DISPATCH] = {c: rate_src["RakshaMarg"][c].assign(rate=lambda d: d.rate * blend_w) for c in contexts}
mults = {"RakshaMarg": {c: model.multiplier_draws(rate_src["RakshaMarg"][c]) for c in contexts},
         # blend = geometric mean of model and braking rate; their disagreement |log w| is extra uncertainty
         DISPATCH: {c: model.multiplier_draws(rate_src[DISPATCH][c], phi=phi_blend, extra_sd=np.abs(np.log(blend_w))) for c in contexts}}
mult = mults[DISPATCH]
true_c = {c: true_rate_ctx(*c) for c in contexts}
L = E.length_km.values
decisions, opt_log, cover, integrity = [], [], [], []
n_od = 0
while n_od < 240:
    o, d = nodes[rng.integers(len(nodes))], nodes[rng.integers(len(nodes))]
    if np.hypot(o[0] - d[0], o[1] - d[1]) < 6:
        continue
    n_od += 1
    ctx = contexts[n_od % len(contexts)]
    for mth, rs in rate_src.items():
        rates = rs[ctx]
        opts = []
        for pth in P.candidate_routes(G, o, d, rates, tb=ctx[0]):
            eids = P.path_edges(G, list(pth))
            sc = P.score_route(eids, rates, E, mult=mults[mth][ctx] if mth in mults else None)
            sc["true"] = float(np.sum(true_c[ctx][eids] * L[eids]) * 1000)
            sc["eids"] = eids
            opts.append(sc)
            if mth in mults:
                cover.append((mth, f"{ctx[0]}/{ctx[1]}", sc["ci90_low"] <= sc["true"] <= sc["ci90_high"]))
        R = P.recommend(opts)
        integrity.append(P.decision_is_consistent(R))
        if R["decision"] == "no_legal_route":
            decisions.append(dict(method=mth, od=(o, d), ctx=ctx, decision="no_legal_route"))
            continue
        Rn = P.recommend(opts, p_required=0.0)                 # same policy without the evidence check
        fastest, choice, nodef = R["fastest"], R["chosen"], Rn["chosen"]
        decisions.append(dict(method=mth, od=(o, d), ctx=ctx, decision=R["decision"], p_safer=R["p_safer"],
                              fastest_true=fastest["true"], choice_true=choice["true"],
                              fastest_time=fastest["time_min"], choice_time=choice["time_min"],
                              nodef_true=nodef["true"], nodef_time=nodef["time_min"],
                              considered_true=R["considered"]["true"] if R["considered"] else None,
                              chosen_eids=" ".join(map(str, choice["eids"])),
                              chosen_exp_per_1000=choice["expected_crashes_per_1000_trips"],
                              chosen_band90=(choice["ci90_low"], choice["ci90_high"]),
                              fastest_exp_per_1000=fastest["expected_crashes_per_1000_trips"]))
        for o_ in opts:
            opt_log.append(dict(method=mth, od=n_od, pred=P.decision_risk(o_), pred_point=o_["expected_crashes_per_1000_trips"], true=o_["true"],
                                time=o_["time_min"], fast_time=fastest["time_min"], fast_true=fastest["true"]))
D_all = pd.DataFrame(decisions)
D = D_all[D_all.decision != "no_legal_route"]
route_eval = {"no_legal_route_trips": {m: int(v) for m, v in (D_all.decision == "no_legal_route").groupby(D_all.method).sum().items()}}
for mth, g in D.groupby("method"):
    sw = g.decision == "switch"
    route_eval[mth] = dict(
        switched_pct=round(100 * sw.mean(), 1), deferred_pct=round(100 * (g.decision == "defer").mean(), 1),
        true_risk_reduction_pct=round(100 * (1 - g.choice_true.sum() / g.fastest_true.sum()), 1),
        extra_travel_time_pct=round(100 * (g.choice_time.sum() / g.fastest_time.sum() - 1), 2),
        switches_truly_safer_pct=round(100 * (g[sw].choice_true < g[sw].fastest_true).mean(), 1) if sw.any() else None)
rk = D[D.method == DISPATCH]                         # the single dispatch scorer used everywhere below
dfr = rk[rk.decision == "defer"]
route_eval["deferral_analysis"] = dict(
    n_trips=int(len(rk)), n_switch=int((rk.decision == "switch").sum()), n_keep=int((rk.decision == "keep").sum()),
    n_defer=int(len(dfr)),
    scorer=DISPATCH,
    deferred_alternatives_truly_safer_pct=round(100 * float((dfr.considered_true < dfr.fastest_true).mean()), 1) if len(dfr) else None,
    switches_truly_safer_pct_without_deferral=round(100 * float((rk[rk.nodef_true != rk.fastest_true].nodef_true <
                                                                    rk[rk.nodef_true != rk.fastest_true].fastest_true).mean()), 1))
cov = pd.DataFrame(cover, columns=["method", "ctx", "hit"])
route_eval["band90_coverage_by_scorer"] = {m: dict(overall=round(100 * float(g.hit.mean()), 1),
                                                   by_context=(100 * g.groupby("ctx").hit.mean()).round(1).to_dict())
                                           for m, g in cov.groupby("method")}
route_eval["band90_coverage_pct"] = route_eval["band90_coverage_by_scorer"][DISPATCH]["overall"]
route_eval["band90_coverage_by_context_pct"] = route_eval["band90_coverage_by_scorer"][DISPATCH]["by_context"]
M["integrity"] = dict(decisions_checked=len(integrity), inconsistent=int(len(integrity) - sum(integrity)))
assert sum(integrity) == len(integrity), "inconsistent decision object"
OL = pd.DataFrame(opt_log)
route_eval["route_score_spearman_vs_truth"] = round(float(stats.spearmanr(OL[OL.method == DISPATCH].pred_point,
                                                                          OL[OL.method == DISPATCH].true).correlation), 3)
# matched time budget: for each per-trip budget pick the lowest PREDICTED-risk option within it
OL = pd.concat([OL, OL[OL.method == DISPATCH].assign(method=DISPATCH + ", point estimate", pred=lambda d: d.pred_point)])
curves = {}
for mth, g in OL.groupby("method"):
    pts = []
    for b in (0, 2, 4, 6, 8, 10, 12, 15, 20, 30):
        ok = g[g.time <= g.fast_time * (1 + b / 100) + 1e-9]
        pick = ok.loc[ok.groupby("od").pred.idxmin()]
        ft = g.groupby("od").fast_true.first(); fti = g.groupby("od").fast_time.first()
        pts.append((round(100 * (pick.time.sum() / fti.loc[pick.od].sum() - 1), 2),
                    round(100 * (1 - pick.true.sum() / ft.loc[pick.od].sum()), 2)))
    curves[mth] = pts
def at_budget(pts, x):
    xs, ys = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    o_ = np.argsort(xs)
    return round(float(np.interp(x, xs[o_], ys[o_])), 1)
route_eval["matched_budget_curves"] = curves
route_eval["true_risk_reduction_at_fleet_extra_time"] = {
    f"+{x}%": {m: at_budget(c, x) for m, c in curves.items()} for x in (1, 2, 4)}
M["evaluation_routes"] = route_eval

# ------------------------------------------------------------------ microbenchmarks (labelled as such)
nr = rate_src[DISPATCH][("night", "clear")]
paths = [P.path_edges(G, nx.shortest_path(G, nodes[rng.integers(len(nodes))], nodes[rng.integers(len(nodes))], weight="time_min")) for _ in range(200)]
ra = nr.rate.values
t = time.time()
for i in range(20000):
    e_ = paths[i % 200]; _ = float(np.dot(ra[e_], L[e_]))
t_sum = (time.time() - t) / 20000 * 1000
t = time.time()
for i in range(20):
    o, d = nodes[rng.integers(len(nodes))], nodes[rng.integers(len(nodes))]
    if o == d:
        continue
    opts = [P.score_route(P.path_edges(G, list(p)), nr, E, mult=mult[("night", "clear")]) for p in P.candidate_routes(G, o, d, nr, tb="night")]
    P.recommend(opts)
t_full = (time.time() - t) / 20 * 1000
M["microbenchmarks"] = dict(note="single CPU core, in-process, 523-segment synthetic graph; not a service load test",
                            cached_route_sum_ms=round(t_sum, 4), full_decision_ms=round(t_full, 1),
                            preprocess_events_per_second=log["events_per_second"])

# ------------------------------------------------------------------ dispatch examples: switch (selected + typical), keep, defer
ref = {c: float(np.median([P.score_route(e_, rate_src["RakshaMarg + braking blend"][c], E)["expected_crashes_per_1000_trips"] for e_ in paths])) for c in contexts}
def build_case(o, d, ctx, label):
    rates = rate_src[DISPATCH][ctx]
    opts = []
    for pth in P.candidate_routes(G, o, d, rates, tb=ctx[0]):
        eids = P.path_edges(G, list(pth))
        sc = P.score_route(eids, rates, E, mult=mults[DISPATCH][ctx])
        sc["true"] = float(np.sum(true_c[ctx][eids] * L[eids]) * 1000)
        sc["risk_index"] = P.risk_index(sc["expected_crashes_per_1000_trips"], ref[ctx])
        opts.append(sc)
    R = P.recommend(opts)
    assert P.decision_is_consistent(R)
    pack = lambda s_: None if s_ is None else dict(
        time_min=round(s_["time_min"], 1), km=round(s_["length_km"], 1), risk_index=round(s_["risk_index"]),
        exp_per_1000=round(s_["expected_crashes_per_1000_trips"], 2), risk_80pct=round(P.decision_risk(s_), 2),
        band90=[round(s_["ci90_low"], 2), round(s_["ci90_high"], 2)], confidence=s_["confidence"],
        true_per_1000=round(s_["true"], 2), eids=[int(e) for e in s_["eids"]])
    return dict(label=label, scorer=DISPATCH, origin=list(o), destination=list(d), context=f"{ctx[0]}/{ctx[1]}",
                decision=R["decision"], p_safer=None if R["p_safer"] is None else round(R["p_safer"], 3),
                n_qualifying=R["n_qualifying"], fastest=pack(R["fastest"]), considered=pack(R["considered"]),
                chosen=pack(R["chosen"]),
                reasons_fastest=P.explain_segments(R["fastest"]["eids"], R["fastest"]["segment_risk"], E, hs, ctx[0]),
                options=[dict(time_min=round(s_["time_min"], 1), risk_index=round(s_["risk_index"], 1),
                              pareto=bool(ip)) for s_, ip in zip(opts, P.pareto(opts))])
cases = {}
best = None                                                   # SELECTED (largest predicted cut) - illustrative only
for o in [n for n in nodes if n[0] <= 1]:
    for d in [n for n in nodes if n[0] >= 20][::2]:
        c_ = build_case(o, d, ("night", "fog"), "selected")
        if c_["decision"] == "switch":
            cut = 1 - c_["chosen"]["exp_per_1000"] / c_["fastest"]["exp_per_1000"]
            if best is None or cut > best[0]:
                best = (cut, c_)
cases["selected_switch"] = best[1]
for dec in ("switch", "keep", "defer"):
    g = rk[rk.decision == dec]
    if len(g) == 0:
        continue
    if dec == "switch":   # typical = median true cut among switches
        cut = 1 - g.choice_true / g.fastest_true
        row = g.iloc[int(np.argsort(cut.values)[len(g) // 2])]
    else:
        row = g.iloc[0]
    cases[f"typical_{dec}"] = build_case(row.od[0], row.od[1], row.ctx, f"typical {dec}")
if "typical_defer" not in cases:
    rng2 = np.random.default_rng(77 + args.seed)
    for _ in range(600):
        o, d = nodes[rng2.integers(len(nodes))], nodes[rng2.integers(len(nodes))]
        if np.hypot(o[0] - d[0], o[1] - d[1]) < 6:
            continue
        c_ = build_case(o, d, contexts[int(rng2.integers(len(contexts)))], "defer (found by searching extra trips)")
        if c_["decision"] == "defer":
            cases["typical_defer"] = c_
            break
for c_ in cases.values():
    if c_["considered"]:
        c_["considered_true_cut_pct"] = round(100 * (1 - c_["considered"]["true_per_1000"] / c_["fastest"]["true_per_1000"]), 1)
    cut_pred = 1 - c_["chosen"]["exp_per_1000"] / c_["fastest"]["exp_per_1000"]
    cut_true = 1 - c_["chosen"]["true_per_1000"] / c_["fastest"]["true_per_1000"]
    c_["predicted_cut_pct"], c_["true_cut_pct"] = round(100 * cut_pred, 1), round(100 * cut_true, 1)
    c_["extra_min"] = round(c_["chosen"]["time_min"] - c_["fastest"]["time_min"], 1)
M["cases"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("options",)} for k, v in cases.items()}
json.dump(cases, open(f"{OUT}/dispatch_cases.json", "w"), indent=1, default=str)

# ------------------------------------------------------------------ T6/T7 outputs
sel = cases["selected_switch"]
lines = [f"# Dispatch card (SIMULATED, selected example) - trip {tuple(sel['origin'])} -> {tuple(sel['destination'])}", "",
         "Context: night departure, fog. Selected as the largest predicted improvement among west-east trips; see",
         "`dispatch_cases.json` for typical switch / keep / defer cases.", "",
         "| Option | Time | Distance | Risk index | Exp. crashes / 1,000 trips (90% band) | Confidence |", "|---|---|---|---|---|---|"]
for lab, s_ in (("Fastest", sel["fastest"]), ("Recommended", sel["chosen"])):
    lines.append(f"| {lab} | {s_['time_min']} min | {s_['km']} km | {s_['risk_index']}/100 | {s_['exp_per_1000']} ({s_['band90'][0]}-{s_['band90'][1]}) | {s_['confidence']} |")
lines += ["", f"Decision: {sel['decision'].upper()} (P(alternative truly safer) = {sel['p_safer']}). Predicted cut {sel['predicted_cut_pct']}%, "
          f"ground-truth cut {sel['true_cut_pct']}%, +{sel['extra_min']} min.", "", "Why the fastest route is risky:"]
for w_ in sel["reasons_fastest"]:
    lines.append(f"- Segment {w_['edge_id']} ({w_['road_class']}, {w_['km']} km, {int(100*w_['risk_share'])}% of route risk): " + "; ".join(w_["reasons"]))
lines += ["", "## Driver brief (template, EN)",
          f"Tonight's route avoids the NH stretch with fog and frequent median openings. Expect {sel['extra_min']:.0f} extra minutes. "
          "Keep a 4-second following distance in fog, use low beam, and do not stop on the carriageway.",
          "", "## ड्राइवर ब्रीफ (टेम्पलेट, हिंदी)",
          f"आज रात का रूट कोहरे और बार-बार मीडियन कट वाले NH हिस्से से बचता है। लगभग {sel['extra_min']:.0f} मिनट ज़्यादा लगेंगे। "
          "कोहरे में आगे की गाड़ी से 4 सेकंड की दूरी रखें, लो-बीम का प्रयोग करें और सड़क पर गाड़ी न रोकें।"]
open(f"{OUT}/dispatch_card.md", "w").write("\n".join(lines))
# T6 trip log: chosen route + risk score per dispatch, ready for post-trip comparison (see api.py /outcome)
log_df = rk.assign(trip_id=[f"T-{i+1:04d}" for i in range(len(rk))], ctx=rk.ctx.astype(str), od=rk.od.astype(str))
log_df["chosen_risk_index"] = [round(P.risk_index(v, ref[c])) for v, c in zip(rk.chosen_exp_per_1000, rk.ctx)]
log_df["fastest_risk_index"] = [round(P.risk_index(v, ref[c])) for v, c in zip(rk.fastest_exp_per_1000, rk.ctx)]
log_df["chosen_band90"] = [f"{lo:.2f}-{hi:.2f}" for lo, hi in rk.chosen_band90]
log_df["scorer"], log_df["source_sha256_12"] = DISPATCH, SHA
log_df[["trip_id", "od", "ctx", "decision", "p_safer", "chosen_eids", "chosen_risk_index", "chosen_exp_per_1000",
        "chosen_band90", "fastest_risk_index", "fastest_time", "choice_time", "scorer", "source_sha256_12"]] \
    .round(3).to_csv(f"{OUT}/dispatch_log.csv", index=False)
# T7 searchable high-risk route records (highest-risk assigned routes)
log_df.sort_values("chosen_risk_index", ascending=False).head(50)[["trip_id", "od", "ctx", "decision", "chosen_risk_index",
    "chosen_exp_per_1000", "chosen_eids"]].round(3).to_csv(f"{OUT}/high_risk_routes.csv", index=False)
ev2 = ev.merge(E[["edge_id", "cls"]], on="edge_id"); ev2["month"] = ev2.timestamp.dt.month
ex = cells.merge(E[["edge_id", "cls"]], on="edge_id").groupby(["month", "cls"]).exposure_vkm.sum()
sev = ev2.assign(s=ev2.event_type.map(P.SEVERITY)).groupby(["month", "cls"]).s.sum()
(sev / ex * 1000).rename("severity_score_per_1k_vkm").reset_index().round(3).to_csv(f"{OUT}/risk_trends_by_month_roadclass.csv", index=False)
xm = (E.x1 + E.x2) / 2
E_reg = E.assign(region=pd.cut(xm, [-np.inf, xm.quantile(1 / 3), xm.quantile(2 / 3), np.inf], labels=["West", "Central", "East"]).astype(str))
ev3 = ev2.merge(E_reg[["edge_id", "region"]], on="edge_id")
ex_r = cells.merge(E_reg[["edge_id", "region"]], on="edge_id").groupby(["month", "region"]).exposure_vkm.sum()
sev_r = ev3.assign(s=ev3.event_type.map(P.SEVERITY)).groupby(["month", "region"]).s.sum()
(sev_r / ex_r * 1000).rename("severity_score_per_1k_vkm").reset_index().round(3).to_csv(f"{OUT}/risk_trends_by_month_region.csv", index=False)
ev2.assign(s=ev2.event_type.map(P.SEVERITY)).groupby("driver_cohort").agg(events=("event_id", "count"), severity=("s", "sum")).assign(note="counts only: per-cohort exposure needs driver-level trip logs").to_csv(f"{OUT}/events_by_driver_cohort.csv")
M["trend_monthly_overall"] = (ev2.assign(s=ev2.event_type.map(P.SEVERITY)).groupby("month").s.sum() /
                              cells.groupby("month").exposure_vkm.sum() * 1000).round(2).tolist()

if not args.no_figures:
    from figures import make_figures, make_demo_html
    heat = {f"{c[0]}/{c[1]}": rate_src[DISPATCH][c].rate.values for c in contexts}
    make_figures(OUT, E, G, model, hs, cases, heat)
    make_demo_html(OUT, E, G, cases, heat)
    pickle.dump(dict(model=model, G=G, edges=E, hotspots=hs, ref=ref, mult=mult, contexts=contexts, blend_w=blend_w, phi_blend=phi_blend, blend_extra_sd=np.abs(np.log(blend_w)),
                     source_sha256_12=SHA, dispatch_scorer=DISPATCH),
                open(f"{OUT}/model_artifacts.pkl", "wb"))

M["runtime_seconds"] = round(time.time() - t0, 1)
json.dump(M, open(f"{OUT}/metrics.json", "w"), indent=2, default=float)
print(json.dumps({k: M[k] for k in ("seed", "eb_k", "dispersion_phi_by_time", "runtime_seconds")}))
print(pd.DataFrame(seg_eval).T.to_string())
print(json.dumps({k: v for k, v in route_eval.items() if k != "matched_budget_curves"}, indent=1))
print({k: (v["decision"], v["predicted_cut_pct"], v["true_cut_pct"], v["extra_min"], v["p_safer"]) for k, v in cases.items()})
