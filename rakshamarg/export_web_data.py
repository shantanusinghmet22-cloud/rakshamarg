"""
export_web_data.py - export the trained RakshaMarg engine for the browser dispatcher console.

    python run_demo.py            # creates outputs/model_artifacts.pkl (primary world)
    python export_web_data.py     # writes web/data_sim.js and tests/fixtures/parity_reference.json

Exports, per departure context (3 time buckets x 3 weathers):
  * dispatch-scorer segment rates (exactly what api.py uses), bootstrap spread, risk-index reference
  * the uncertainty ingredients (dispersion, Empirical-Bayes shrink, scorer disagreement, road-class codes)
  * a cold-start model for real OSM roads: the log-linear Poisson GLM of the road-features-only model
  * Python reference decisions for ~300 trips, used by tests/test_engine.mjs to check the browser engine
"""
import json, os, pickle, hashlib, glob
import numpy as np
import pandas as pd
import networkx as nx

from rakshamarg import pipeline as P
from rakshamarg.world import simulate, TIME_BUCKETS, WEATHERS, SPEED

ART = pickle.load(open("outputs/model_artifacts.pkl", "rb"))
model, G, E, HS = ART["model"], ART["G"], ART["edges"], ART["hotspots"]
os.makedirs("web", exist_ok=True); os.makedirs("tests/fixtures", exist_ok=True)
CTX = [(tb, w) for tb in TIME_BUCKETS for w in WEATHERS]


def ctx_rates(tb, w):
    r = model.edge_rates(tb, w)
    return r.assign(rate=r.rate * ART["blend_w"])


def ctx_ref(tb, w, rates):                     # identical to api.py
    return ART["ref"].get((tb, w), float(np.median(rates.rate) * 30 * 1000))


# ---------------------------------------------------------------- network
node_id = {n: f"{n[0]},{n[1]}" for n in G.nodes}
nodes = [dict(id=node_id[n], x=round(G.nodes[n]["x"], 4), y=round(G.nodes[n]["y"], 4)) for n in G.nodes]
cls_codes, cls_names = pd.factorize(E.cls.values)              # same order as multiplier_draws
edges = []
for r in E.itertuples():
    edges.append([int(r.edge_id), node_id[r.u], node_id[r.v], r.cls, round(r.length_km, 6), round(r.time_min, 6),
                  round(r.curvature_deg_km, 2), round(r.junctions_per_km, 2), round(r.median_openings_per_km, 2),
                  int(r.lit), round(r.gradient_pct, 2), int(r.market_zone), int(r.public_blackspot),
                  int(r.truck_no_entry_day), round(r.x1, 4), round(r.y1, 4), round(r.x2, 4), round(r.y2, 4)])
assert [e[0] for e in edges] == list(range(len(edges)))

import base64
MQ = 4000.0   # log-multipliers stored as int16 with step 1/4000 (relative error <= 1.25e-4)
contexts = {}
for tb, w in CTX:
    rates = ctx_rates(tb, w)
    M_ = model.multiplier_draws(rates, phi=ART["phi_blend"], extra_sd=ART["blend_extra_sd"])     # exactly api.py
    q = np.round(np.log(M_) * MQ)
    assert np.abs(q).max() < 32767
    contexts[f"{tb}/{w}"] = dict(mult_b64=base64.b64encode(q.astype("<i2").tobytes()).decode(), mult_shape=list(M_.shape), mult_q=MQ,
        rate=[float(f"{v:.6e}") for v in rates.rate.values],
        boot_sd=[round(float(v), 5) for v in rates.boot_sd.values],
        ref=float(ctx_ref(tb, w, rates)),
        sd_ctx=float(1.0 / np.sqrt(max(model.ctx_n.get((tb, w), 0), 1))))
shrink = (model.k / (model.k + model.eb.observed.values)).tolist()
unc = dict(phi_blend=ART["phi_blend"], shrink=[round(v, 5) for v in shrink],
           extra_sd=[round(float(v), 5) for v in ART["blend_extra_sd"]], cls_codes=[int(c) for c in cls_codes],
           n_cls=int(cls_codes.max() + 1), S=400, q_decision=P.RISK_AVERSE_Q)
hs = HS[["rank", "x_km", "y_km", "road_class", "crashes", "near_misses", "harsh_brakes", "night_share",
         "risk_rank_score", "public_blackspot"]].round(3).to_dict(orient="records")

# ---------------------------------------------------------------- cold-start model for real roads (GLM only)
W = simulate(seed=7, fidelity="faithful")
ev, _ = P.preprocess(W["events"], W["edges"])
asof = pd.Timestamp("2025-10-01")
c_tr, c_te = W["cells"][W["cells"].month <= 9], W["cells"][W["cells"].month >= 10]
geo = P.RiskModel(use_telematics=False, use_eb=False).fit(c_tr, ev[ev.timestamp < asof], W["edges"], asof)
glm = geo.gbm.glm
sc, pr = glm.named_steps["standardscaler"], glm.named_steps["poissonregressor"]
te = c_te[c_te.exposure_vkm > 0]
Xte, _ = geo._design(te, W["edges"], geo.sur)
glm_rate = glm.predict(Xte) * geo.scale
phi_cold = P.dispersion_from_rates(te, glm_rate)
cold = dict(features=geo.cols, mean=sc.mean_.round(6).tolist(), scale=sc.scale_.round(6).tolist(),
            coef=pr.coef_.round(6).tolist(), intercept=round(float(pr.intercept_), 6), crash_scale=float(geo.scale),
            phi_holdout_months=phi_cold, transfer_var=0.25, speed=SPEED,
            note="Road-features-only Poisson GLM (no fleet data). Rates are relative: trained on the simulated region.")

# ---------------------------------------------------------------- analytics + evidence
trend_reg = pd.read_csv("outputs/risk_trends_by_month_region.csv").to_dict(orient="records")
trend_cls = pd.read_csv("outputs/risk_trends_by_month_roadclass.csv").to_dict(orient="records")
H = json.load(open("outputs/holdout_summary.json")); D = json.load(open("outputs/multiseed_summary.json"))
BL = "RakshaMarg + braking blend"
evidence = {}
for nm, S_ in (("holdout", H), ("development", D)):
    evidence[nm] = {f: dict(seg_model=S_[f]["segments"]["RakshaMarg (full)"]["spearman_segments"]["mean"],
                            seg_braking=S_[f]["segments"]["Harsh brakes per veh-km (smoothed)"]["spearman_segments"]["mean"],
                            mb2_blend=S_[f]["matched_budget"][BL]["+2%"]["mean"], mb2_braking=S_[f]["matched_budget"]["Harsh brakes per veh-km"]["+2%"]["mean"],
                            mb2_crash=S_[f]["matched_budget"]["Crash history"]["+2%"]["mean"],
                            policy_cut=S_[f]["policy"][BL]["true_risk_reduction_pct"]["mean"],
                            policy_time=S_[f]["policy"][BL]["extra_travel_time_pct"]["mean"],
                            safer=S_[f]["policy"][BL]["switches_truly_safer_pct"]["mean"],
                            coverage=S_[f]["band90_coverage"]["mean"]) for f in ("faithful", "noisy")}
    evidence[nm]["deferral"] = S_["deferral_all_worlds"]; evidence[nm]["integrity"] = S_["integrity"]

meta = dict(source_sha256_12=ART["source_sha256_12"], dispatch_scorer=ART["dispatch_scorer"],
            model_crash_scale=float(model.scale), speed=SPEED, n_segments=len(E))
data = dict(meta=meta, nodes=nodes, edges=edges, edge_cols=["id", "u", "v", "cls", "len", "time", "curv", "junc", "median",
            "lit", "grad", "market", "blackspot", "noentry", "x1", "y1", "x2", "y2"], cls_names=list(cls_names),
            contexts=contexts, unc=unc, hotspots=hs, cold=cold, trend_region=trend_reg, trend_class=trend_cls,
            evidence=evidence, cases=json.load(open("outputs/dispatch_cases.json")))
raw = json.dumps(data, separators=(",", ":"))
open("web/data_sim.js", "w").write("window.RM_SIM = " + raw + ";\n")
os.makedirs("model", exist_ok=True); open("model/rakshamarg_model_v1.json", "w").write(raw)   # served by api.py; versioned model

# ---------------------------------------------------------------- Python reference decisions (exactly api.py logic)
rng = np.random.default_rng(2026)
nl = list(G.nodes)
refs = []
mult_cache = {}
while len(refs) < 300:
    o, d = nl[rng.integers(len(nl))], nl[rng.integers(len(nl))]
    if o == d or np.hypot(o[0] - d[0], o[1] - d[1]) < 4:
        continue
    tb, w = CTX[len(refs) % len(CTX)]
    rates = ctx_rates(tb, w)
    if (tb, w) not in mult_cache:
        mult_cache[(tb, w)] = model.multiplier_draws(rates, phi=ART["phi_blend"], extra_sd=ART["blend_extra_sd"])
    opts = [P.score_route(P.path_edges(G, list(p)), rates, E, mult=mult_cache[(tb, w)])
            for p in P.candidate_routes(G, o, d, rates, tb=tb)]
    R = P.recommend(opts)
    refs.append(dict(o=node_id[o], d=node_id[d], ctx=f"{tb}/{w}", candidates=[list(map(int, x["eids"])) for x in opts],
                     point=[x["expected_crashes_per_1000_trips"] for x in opts],
                     q80=[x["risk_averse"] for x in opts], decision=R["decision"], p=R["p_safer"],
                     fastest=None if R["fastest"] is None else list(map(int, R["fastest"]["eids"])),
                     chosen=None if R["chosen"] is None else list(map(int, R["chosen"]["eids"])),
                     considered=None if R["considered"] is None else list(map(int, R["considered"]["eids"]))))
json.dump(dict(source_sha256_12=ART["source_sha256_12"], trips=refs), open("tests/fixtures/parity_reference.json", "w"))
print(f"web/data_sim.js {os.path.getsize('web/data_sim.js')/1e6:.2f} MB | contexts {len(contexts)} | parity trips {len(refs)} "
      f"| decisions {pd.Series([r['decision'] for r in refs]).value_counts().to_dict()} | cold phi {phi_cold} | cols {geo.cols}")
