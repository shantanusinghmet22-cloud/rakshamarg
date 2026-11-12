"""Supplementary analysis (does not change the released model).
On the 10 holdout worlds:
  (a) the reviewer's challenger baselines: smoothed severe events (near-misses + crashes) per veh-km, context-free and
      context-aware; context-aware braking per veh-km;
  (b) data-pipeline sensitivity (review F12): refit the model on event counts derived from the cleaned, map-matched
      event records instead of the simulator's ideal per-edge aggregates.
Metric: Spearman rank correlation with true segment risk (day/clear) and across segment x 9 contexts."""
import json, glob, os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from scipy import stats
from rakshamarg.world import simulate, context_multiplier, CONFIG, TIME_BUCKETS, WEATHERS
from rakshamarg import pipeline as P
warnings.filterwarnings("ignore")
rows = []
for f in sorted(glob.glob("outputs/holdout/*/metrics.json")):
    M = json.load(open(f)); seed, fid, k = M["seed"], M["surrogate_fidelity"], M["eb_k"]
    W = simulate(seed=seed, fidelity=fid); E, cells = W["edges"], W["cells"]; base = CONFIG["base_crash_rate"]
    ev, _ = P.preprocess(W["events"], E); asof = pd.Timestamp(f"{CONFIG['year']}-10-01"); ev_tr = ev[ev.timestamp < asof]
    c_tr = cells[cells.month <= 9]
    grid = pd.DataFrame([(e, tb, w) for tb in TIME_BUCKETS for w in WEATHERS for e in E.edge_id], columns=["edge_id", "tb", "weather"])
    grid["true"] = np.concatenate([base * E.true_rel_risk.values * context_multiplier(E, tb, w) for tb in TIME_BUCKETS for w in WEATHERS])
    dc = grid[(grid.tb == "day") & (grid.weather == "clear")]
    sp = lambda pred, g: float(stats.spearmanr(pred, g.true).correlation)
    def score(fn): return dict(seg=sp(fn(dc), dc), seg_ctx=sp(fn(grid), grid))
    # (a) baselines from training-period aggregates
    agg = c_tr.groupby("edge_id")[["n_crash", "n_near_miss", "n_harsh_brake", "exposure_vkm"]].sum().reindex(E.edge_id).fillna(0)
    def smoothed(cnt): g0 = cnt.sum() / agg.exposure_vkm.sum(); return ((cnt + g0 * 5000) / (agg.exposure_vkm + 5000)).values
    sev, brk = smoothed(agg.n_crash + agg.n_near_miss), smoothed(agg.n_harsh_brake)
    cx = c_tr.assign(sev=c_tr.n_crash + c_tr.n_near_miss).groupby(["tb", "weather"])[["sev", "n_harsh_brake", "exposure_vkm"]].sum()
    ctx_sev = (cx.sev / cx.exposure_vkm) / (cx.sev.sum() / cx.exposure_vkm.sum()); ctx_brk = (cx.n_harsh_brake / cx.exposure_vkm) / (cx.n_harsh_brake.sum() / cx.exposure_vkm.sum())
    cm = lambda tab: (lambda g: tab.reindex(pd.MultiIndex.from_arrays([g.tb, g.weather])).fillna(1.0).values)
    res = {"Severe events per veh-km (smoothed)": score(lambda g: sev[g.edge_id.values]),
           "Severe events per veh-km x context": score(lambda g: sev[g.edge_id.values] * cm(ctx_sev)(g)),
           "Braking per veh-km x context": score(lambda g: brk[g.edge_id.values] * cm(ctx_brk)(g))}
    # released model (k from the saved run) and the same model refit on observed (cleaned, snapped) event counts
    m_rel = P.RiskModel(k=k).fit(c_tr, ev_tr, E, asof); res["RakshaMarg model (released pipeline)"] = score(m_rel.predict_cells)
    evm = ev.assign(month=ev.timestamp.dt.month)
    obs = evm.groupby(["edge_id", "month", "weather", "tb", "event_type"]).size().unstack(fill_value=0)
    obs.columns = [f"n_{c}" for c in obs.columns]; obs = obs.reset_index()
    c_obs = cells.drop(columns=[c for c in cells.columns if c.startswith("n_")]).merge(obs, on=["edge_id", "month", "weather", "tb"], how="left").fillna(0)
    m_obs = P.RiskModel(k=k).fit(c_obs[c_obs.month <= 9], ev_tr, E, asof); res["RakshaMarg model (counts from cleaned events)"] = score(m_obs.predict_cells)
    for name, v in res.items(): rows.append(dict(seed=seed, fidelity=fid, method=name, **v))
    print(seed, fid, {k_: round(v["seg"], 3) for k_, v in res.items()}, flush=True)
df = pd.DataFrame(rows); df.to_csv("outputs/supplementary/extra_baselines_per_world.csv", index=False)
summ = df.groupby(["fidelity", "method"]).agg(seg_mean=("seg", "mean"), seg_sd=("seg", "std"), ctx_mean=("seg_ctx", "mean"), ctx_sd=("seg_ctx", "std")).round(3)
summ.to_csv("outputs/supplementary/extra_baselines_summary.csv"); print(summ.to_string())
