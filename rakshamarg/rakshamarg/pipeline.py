"""
pipeline.py - RakshaMarg core: the 8 tasks of the Fleet Route Risk Intelligence theme.

  1  preprocess()            clean + de-duplicate + map-match telematics to road segments
  2  detect_hotspots()       severity- & recency-weighted density clustering (DBSCAN)
  3  RiskModel               exposure-normalised crash-rate model:
                               SPF prior (road features)  x  telematics surrogates  x
                               Empirical-Bayes correction with observed crashes  ->  rate + uncertainty
     score_route()           route risk for a departure time-bucket and weather, with CI + reasons
  4  recommend()             k-alternatives, Pareto frontier, fleet risk-vs-time policy
  5-7 handled in demo/report (heatmap, dispatch card, trend tables)
  8  evaluation in evaluate.py
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import networkx as nx
from scipy.spatial import cKDTree
from scipy import stats
from sklearn.cluster import DBSCAN
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline


class GLMBoost:
    """Log-linear Poisson GLM (extrapolates: risk can scale with surrogate rates beyond the training range)
    times a gradient-boosted multiplicative residual (captures interactions the GLM misses)."""

    def __init__(self, seed=0, use_glm=True):
        self.seed, self.use_glm = seed, use_glm

    def fit(self, X, y, sample_weight):
        w = sample_weight
        if self.use_glm:
            self.glm = make_pipeline(StandardScaler(), PoissonRegressor(alpha=1e-3, max_iter=2000))
            self.glm.fit(X, y, poissonregressor__sample_weight=w)
            g = np.clip(self.glm.predict(X), 1e-15, None)
        else:
            self.glm, g = None, np.full(len(y), np.average(y, weights=w))
            self.const = g[0]
        self.gbm = HistGradientBoostingRegressor(loss="poisson", max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                                 min_samples_leaf=40, l2_regularization=1.0, random_state=self.seed)
        self.gbm.fit(X, y / g, sample_weight=w * g)
        return self

    def predict(self, X):
        g = np.clip(self.glm.predict(X), 1e-15, None) if self.glm is not None else self.const
        return g * self.gbm.predict(X)

from .world import TIME_BUCKETS, WEATHERS

SEVERITY = {"crash": 10.0, "near_miss": 4.0, "harsh_brake": 1.0, "harsh_turn": 0.8, "harsh_accel": 0.3}
SURROGATES = ["harsh_brake", "harsh_turn", "harsh_accel", "near_miss"]
ROAD_FEATURES = ["curvature_deg_km", "junctions_per_km", "median_openings_per_km", "lit",
                 "gradient_pct", "market_zone", "speed_kmph", "public_blackspot"]


# --------------------------------------------------------------------------- 1. preprocess
def preprocess(events: pd.DataFrame, edges: pd.DataFrame, step_m: float = 25.0, max_snap_m: float = 60.0):
    """Clean raw telematics and snap each event to a road segment.

    Real deployment would use HMM map-matching on the GPS trace (e.g. Valhalla/OSRM `match`);
    events here are single points, so nearest-segment snapping on a 25 m densified KD-tree is used.
    """
    log = {"raw_rows": int(len(events))}
    ev = events.copy()
    bbox = (edges[["x1", "x2"]].values.min() - 1, edges[["x1", "x2"]].values.max() + 1,
            edges[["y1", "y2"]].values.min() - 1, edges[["y1", "y2"]].values.max() + 1)
    null_island = (ev.x_km.abs() < 1e-6) & (ev.y_km.abs() < 1e-6)
    out_box = ~ev.x_km.between(bbox[0], bbox[1]) | ~ev.y_km.between(bbox[2], bbox[3])
    bad_speed = ev.speed_kmph > 150
    log["dropped_null_or_out_of_bbox"] = int((null_island | out_box).sum())
    log["dropped_impossible_speed"] = int((bad_speed & ~(null_island | out_box)).sum())
    ev = ev[~(null_island | out_box | bad_speed)]
    before = len(ev)
    ev = ev.drop_duplicates(subset=["vehicle_id", "timestamp", "event_type"])
    log["dropped_duplicates"] = int(before - len(ev))

    # densify segments into points
    pts, ids = [], []
    for r in edges.itertuples():
        n = max(2, int(np.hypot(r.x2 - r.x1, r.y2 - r.y1) * 1000 / step_m))
        t = np.linspace(0, 1, n)
        pts.append(np.c_[r.x1 + t * (r.x2 - r.x1), r.y1 + t * (r.y2 - r.y1)])
        ids.append(np.full(n, r.edge_id))
    tree = cKDTree(np.vstack(pts))
    ids = np.concatenate(ids)
    d, k = tree.query(ev[["x_km", "y_km"]].values)
    ev = ev.assign(edge_id=ids[k], snap_dist_m=d * 1000)
    far = ev.snap_dist_m > max_snap_m
    log["dropped_unmatched"] = int(far.sum())
    ev = ev[~far].copy()
    if "true_edge" in ev:
        log["map_match_accuracy"] = float((ev.edge_id == ev.true_edge).mean())
    log["clean_rows"] = int(len(ev))
    ev["tb"] = pd.cut(((ev.timestamp.dt.hour - 6) % 24), [-1, 11, 15, 23], labels=TIME_BUCKETS).astype(str)
    return ev, log


# --------------------------------------------------------------------------- 2. hotspots
def detect_hotspots(ev: pd.DataFrame, edges: pd.DataFrame, cells: pd.DataFrame, asof: pd.Timestamp,
                    tau_days: float = 120.0, cell_m: float = 100.0, eps_km: float = 0.35,
                    min_cells: int = 3):
    """Severity x recency weighted DBSCAN on 100 m micro-cells (scales to millions of events)."""
    age = (asof - ev.timestamp).dt.total_seconds() / 86400
    w = ev.event_type.map(SEVERITY).values * np.exp(-age.clip(lower=0) / tau_days)
    gx = np.floor(ev.x_km * 1000 / cell_m).astype(int)
    gy = np.floor(ev.y_km * 1000 / cell_m).astype(int)
    mc = pd.DataFrame({"gx": gx, "gy": gy, "w": w, "edge_id": ev.edge_id.values,
                       "crash": (ev.event_type == "crash").values, "nm": (ev.event_type == "near_miss").values,
                       "hb": (ev.event_type == "harsh_brake").values, "night": (ev.tb != "day").values})
    agg = mc.groupby(["gx", "gy"]).agg(w=("w", "sum"), crashes=("crash", "sum"), near_miss=("nm", "sum"),
                                         harsh_brake=("hb", "sum"), night_share=("night", "mean"),
                                         edge=("edge_id", lambda s: s.mode().iloc[0])).reset_index()
    # exposure of each micro-cell = exposure density of its segment x cell length (count -> RATE)
    expo_edge = cells.groupby("edge_id").exposure_vkm.sum()
    dens = (expo_edge / edges.set_index("edge_id").length_km).reindex(agg.edge).fillna(0).values
    agg["exposure_vkm"] = dens * cell_m / 1000
    med = agg.w.sum() / max(agg.exposure_vkm.sum(), 1)
    m = 500.0
    agg["rate"] = (agg.w + m * med) / (agg.exposure_vkm + m)          # EB-smoothed severity rate
    thr = agg.rate.quantile(0.90)
    cand = agg.rate.values >= thr
    X = np.c_[(agg.gx + 0.5) * cell_m / 1000, (agg.gy + 0.5) * cell_m / 1000]
    lab = np.full(len(agg), -1)
    if cand.sum() >= 3:
        lab[cand] = DBSCAN(eps=eps_km, min_samples=min_cells).fit(X[cand]).labels_
    agg["cluster"] = lab
    hs = []
    for cid, g in agg[agg.cluster >= 0].groupby("cluster"):
        eids = g.edge.unique()
        expo = float(expo_edge.reindex(eids).fillna(0).sum())
        cx, cy = np.average(X[g.index, 0], weights=g.w), np.average(X[g.index, 1], weights=g.w)
        dom = edges.set_index("edge_id").loc[eids]
        hs.append(dict(hotspot_id=int(cid), x_km=cx, y_km=cy, weighted_score=float(g.w.sum()),
                       crashes=int(g.crashes.sum()), near_misses=int(g.near_miss.sum()),
                       harsh_brakes=int(g.harsh_brake.sum()), night_share=float(np.average(g.night_share, weights=g.w)),
                       exposure_vkm=expo, score_per_1k_vkm=float(g.w.sum() / max(expo, 1) * 1000),
                       road_class=dom.cls.mode().iloc[0], n_segments=len(eids),
                       public_blackspot=int(dom.public_blackspot.max())))
    hs = pd.DataFrame(hs)
    if len(hs):
        # rank by exposure-normalised score, shrunk toward the median for low-exposure clusters
        med = hs.score_per_1k_vkm.median()
        k = 20000.0
        hs["risk_rank_score"] = (hs.weighted_score * 1000 + k * med) / (hs.exposure_vkm + k)
        hs = hs.sort_values("risk_rank_score", ascending=False).reset_index(drop=True)
        hs["rank"] = np.arange(1, len(hs) + 1)
    return hs, agg


# --------------------------------------------------------------------------- 3. risk model
class RiskModel:
    """Exposure-normalised crash-rate model with Empirical-Bayes correction.

    rate(edge, tb, weather) = SPF_GBM(road features, context, telematics surrogates) * EB_factor(edge)
    EB_factor ~ Gamma(k + crashes_obs, k + crashes_expected)   (Hauer / HSM style)
    """

    def __init__(self, k: float = 4.0, m_vkm: float = 5000.0, use_telematics: bool = True,
                 use_eb: bool = True, recency_tau_days: float = 240.0, n_boot: int = 0,
                 target: str = "severe", use_glm: bool = True):
        self.k, self.m, self.use_tel, self.use_eb, self.tau = k, m_vkm, use_telematics, use_eb, recency_tau_days
        self.n_boot = n_boot
        self.use_glm = use_glm
        self.target = target   # "severe": learn from near-misses + crashes (~50x more data), calibrate to crashes

    # ---- feature construction
    def _edge_surrogates(self, ev, cells, edges, asof):
        expo = cells.groupby("edge_id").exposure_vkm.sum().reindex(edges.edge_id).fillna(0).values
        out = pd.DataFrame({"edge_id": edges.edge_id.values, "exposure_vkm": expo})
        age = (asof - ev.timestamp).dt.total_seconds() / 86400
        ev = ev.assign(rw=np.exp(-age.clip(lower=0) / self.tau))
        n_total = np.zeros(len(edges))
        for t in SURROGATES:
            c = ev[ev.event_type == t].groupby("edge_id").rw.sum().reindex(edges.edge_id).fillna(0).values
            n_total += c
            # class-level prior rate, then EB smoothing of each edge's surrogate rate
            prior = pd.Series(c).groupby(edges.cls.values).transform("sum") / \
                    pd.Series(expo).groupby(edges.cls.values).transform("sum").clip(lower=1)
            out[f"r_{t}"] = np.log((c + self.m * prior.values) / (expo + self.m) * 1000 + 1e-6)
        out["n_surrogate"] = n_total
        return out

    def _design(self, frame, edges, sur):
        X = frame[["edge_id", "tb", "weather"]].merge(edges[["edge_id"] + ROAD_FEATURES], on="edge_id", how="left")
        for tb in TIME_BUCKETS[1:]:
            X[f"tb_{tb}"] = (X.tb == tb).astype(int)
        for w in WEATHERS[1:]:
            X[f"w_{w}"] = (X.weather == w).astype(int)
        X["unlit_dark"] = ((X.lit == 0) & (X.tb != "day")).astype(int)
        if self.use_tel:
            X = X.merge(sur.drop(columns=["exposure_vkm", "n_surrogate"]), on="edge_id", how="left")
        cols = [c for c in X.columns if c not in ("edge_id", "tb", "weather")]
        return X[cols].values.astype(float), cols

    # ---- fit
    def fit(self, cells_tr, ev_tr, edges, asof):
        self.edges = edges
        self.sur = self._edge_surrogates(ev_tr, cells_tr, edges, asof)
        tr = cells_tr[cells_tr.exposure_vkm > 0]
        X, self.cols = self._design(tr, edges, self.sur)
        if self.target == "severe":
            cnt = tr.n_crash.values + tr.n_near_miss.values
        else:
            cnt = tr.n_crash.values
        y = cnt / tr.exposure_vkm.values
        mk = lambda seed: GLMBoost(seed=seed, use_glm=self.use_glm)
        self.gbm = mk(0).fit(X, y, sample_weight=tr.exposure_vkm.values)
        # epistemic uncertainty: bootstrap ensemble, resampling whole road segments
        self.boot = []
        rng = np.random.default_rng(0)
        ids = edges.edge_id.values
        for b in range(self.n_boot):
            pick = pd.Series(rng.choice(ids, len(ids))).value_counts()
            wb = pick.reindex(tr.edge_id.values).fillna(0).values
            self.boot.append(mk(b + 1).fit(X, y, sample_weight=tr.exposure_vkm.values * wb))
        # context-sparsity: Poisson uncertainty of how well each (time, weather) context is learned
        self.ctx_n = tr.groupby(["tb", "weather"]).n_crash.sum().to_dict()
        # calibrate severe-event rate to crash rate (single fleet-level ratio, learned on training data)
        self.scale = tr.n_crash.sum() / max(float(np.sum(self.gbm.predict(X) * tr.exposure_vkm.values)), 1e-12)
        mu = self.gbm.predict(X) * self.scale
        exp_crash = pd.Series(mu * tr.exposure_vkm.values).groupby(tr.edge_id.values).sum()
        obs_crash = tr.groupby("edge_id").n_crash.sum()
        e = pd.DataFrame({"expected": exp_crash, "observed": obs_crash}).reindex(edges.edge_id).fillna(0)
        if self.use_eb:
            k_edge = self.k * (1 + self.sur.set_index("edge_id").n_surrogate.reindex(e.index).values / 200)
            e["alpha"] = k_edge + e.observed
            e["beta"] = k_edge + e.expected
        else:
            e["alpha"], e["beta"] = 1e6, 1e6
        e["factor"] = e.alpha / e.beta
        # Gamma posterior coefficient of variation; surrogates sharpen the mean but we do not let them
        # shrink the interval (they are proxies, not crashes) -> deliberately conservative
        e["rel_sd"] = 1 / np.sqrt((self.k if self.use_eb else 1e6) + e.observed)
        self.eb = e
        return self

    def edge_rates(self, tb="day", weather="clear"):
        """Crash rate per veh-km for every edge under a context, plus relative s.d."""
        fr = pd.DataFrame({"edge_id": self.edges.edge_id, "tb": tb, "weather": weather})
        X, _ = self._design(fr, self.edges, self.sur)
        base = self.gbm.predict(X) * self.scale
        r = base * self.eb.factor.values
        boot_sd = np.zeros(len(r))
        if self.boot:
            B = np.array([g.predict(X) for g in self.boot]) * self.scale
            boot_sd = np.std(np.log(np.clip(B, 1e-15, None)), axis=0)
        return pd.DataFrame({"edge_id": self.edges.edge_id.values, "rate": r, "boot_sd": boot_sd,
                             "rel_sd": np.sqrt(self.eb.rel_sd.values ** 2 + boot_sd ** 2), "tb": tb, "weather": weather})

    # ---- uncertainty: dispersion measured on held-out validation months (observable, not simulated truth)
    def estimate_dispersion(self, cells_val):
        v = cells_val[cells_val.exposure_vkm > 0]
        return dispersion_from_rates(v, self.predict_cells(v))

    def multiplier_draws(self, rates, S=400, phi=None, extra_sd=None):
        """extra_sd: optional per-segment log-sd, e.g. disagreement between the two scorers in a blend."""
        """S x n_edges matrix of multiplicative rate errors for one context. Shared draws make route
        comparisons *paired*: errors common to both routes cancel."""
        tb, weather = rates.tb.iloc[0], rates.weather.iloc[0]
        rng = np.random.default_rng(1000 + 10 * TIME_BUCKETS.index(tb) + WEATHERS.index(weather))
        phi = (phi if phi is not None else getattr(self, "phi", {})).get(tb, 0.3)
        shrink = self.k / (self.k + self.eb.observed.values)           # crash-rich segments are surer
        sd = np.sqrt(phi * shrink + rates.boot_sd.values ** 2 + (0 if extra_sd is None else np.asarray(extra_sd) ** 2))
        cls = pd.factorize(self.edges.cls.values)[0]
        z_cls = rng.standard_normal((S, cls.max() + 1))[:, cls]       # errors shared within a road class
        z_ind = rng.standard_normal((S, len(sd)))
        sd_ctx = 1.0 / np.sqrt(max(getattr(self, "ctx_n", {}).get((tb, weather), 0), 1))
        z_ctx = rng.standard_normal((S, 1))                            # how well this context is learned
        logm = sd * (np.sqrt(0.5) * z_cls + np.sqrt(0.5) * z_ind) + sd_ctx * z_ctx - 0.5 * (sd ** 2 + sd_ctx ** 2)
        return np.exp(logm)

    def predict_cells(self, cells):
        X, _ = self._design(cells, self.edges, self.sur)
        return self.gbm.predict(X) * self.scale * self.eb.factor.reindex(cells.edge_id).values


def dispersion_from_rates(v, rate):
    """Method-of-moments negative-binomial dispersion of a scorer's predictions on held-out cells, by time bucket.
    Uses only observable data (exposure, observed crashes), so it can be computed in deployment too."""
    mu = rate * v.exposure_vkm.values
    df = pd.DataFrame({"edge": v.edge_id.values, "tb": v.tb.values, "mu": mu, "y": v.n_crash.values}) \
        .groupby(["tb", "edge"])[["mu", "y"]].sum().reset_index()
    phi = {}
    for tb, g in df.groupby("tb"):
        num = ((g.y - g.mu) ** 2 - g.y).sum()
        phi[tb] = float(np.clip(num / max((g.mu ** 2).sum(), 1e-12), 0.02, 4.0))
    return phi


# --------------------------------------------------------------------------- route scoring
def path_edges(G, path):
    return [G.edges[a, b]["edge_id"] for a, b in zip(path[:-1], path[1:])]


def score_route(eids, rates: pd.DataFrame, edges: pd.DataFrame, trips: int = 1000, mult=None):
    eids = list(eids)
    rate = rates.rate.values[eids]
    L = edges.length_km.values[eids]
    seg = rate * L * trips                                            # expected crashes per `trips` trips
    total = float(seg.sum())
    out = dict(eids=eids, expected_crashes_per_1000_trips=total, time_min=float(edges.time_min.values[eids].sum()),
               length_km=float(L.sum()), segment_risk=seg, draws=None,
               ci90_low=None, ci90_high=None, confidence="n/a", rel_width=None)
    if mult is not None:
        d = mult[:, eids] @ seg
        lo, hi = np.quantile(d, [0.05, 0.95])
        w = (hi - lo) / max(total, 1e-12)
        out.update(draws=d, ci90_low=float(lo), ci90_high=float(hi), rel_width=float(w),
                   risk_averse=float(np.quantile(d, RISK_AVERSE_Q)),
                   confidence="High" if w < 0.6 else ("Medium" if w < 1.2 else "Low"))
    return out


RISK_AVERSE_Q = 0.8   # decisions use the 80th-percentile risk: guards against the optimizer's curse


def decision_risk(o):
    """Risk used for decisions: pessimistic (80th pct of paired draws) when uncertainty is available."""
    return o.get("risk_averse") if o.get("draws") is not None else o["expected_crashes_per_1000_trips"]


def risk_index(expected_per_1000, ref):
    """0-100 index, 50 == fleet-median route risk for that context."""
    return float(100 * (1 - np.exp(-np.log(2) * expected_per_1000 / ref)))


def explain_segments(eids, seg_risk, edges, hotspots, tb, top=3):
    L = edges.set_index("edge_id").loc[eids].reset_index()
    L["risk"] = seg_risk
    L["share"] = L.risk / L.risk.sum()
    out = []
    for r in L.sort_values("risk", ascending=False).head(top).itertuples():
        why = []
        if r.curvature_deg_km > 60:
            why.append(f"sharp curves ({r.curvature_deg_km:.0f} deg/km)")
        if r.gradient_pct > 3:
            why.append(f"steep gradient ({r.gradient_pct:.1f}%)")
        if r.median_openings_per_km > 1.2:
            why.append(f"{r.median_openings_per_km:.1f} median openings/km (U-turn & wrong-side conflicts)")
        if r.junctions_per_km > 2.5:
            why.append(f"dense junctions ({r.junctions_per_km:.1f}/km)")
        if r.lit == 0 and tb != "day":
            why.append("unlit stretch after dark")
        if r.market_zone:
            why.append("market zone (pedestrians, parked vehicles)")
        if r.public_blackspot:
            why.append("on public black-spot list")
        if len(hotspots):
            mx, my = (r.x1 + r.x2) / 2, (r.y1 + r.y2) / 2
            d = np.hypot(hotspots.x_km - mx, hotspots.y_km - my)
            if d.min() < 1.2:
                h = hotspots.iloc[int(d.argmin())]
                why.append(f"fleet hotspot #{int(h['rank'])}: {int(h.harsh_brakes)} harsh brakes, {int(h.near_misses)} near-misses")
        out.append(dict(edge_id=int(r.edge_id), road_class=r.cls, km=round(r.length_km, 1),
                        risk_share=round(float(r.share), 3), reasons=why or ["elevated fleet event rate"]))
    return out


# --------------------------------------------------------------------------- 4. alternatives
def truck_graph(G, tb):
    """Remove city no-entry streets for heavy vehicles during the restricted window (06-22 h)."""
    if tb == "night":
        return G
    return nx.subgraph_view(G, filter_edge=lambda u, v: not G.edges[u, v].get("no_entry_day", False))


def candidate_routes(G, o, d, rates, k_fast=4, alphas=(0.5, 1, 2, 4, 8), tb=None):
    """k fastest simple paths + risk-penalised shortest paths (cost = minutes + alpha * risk-minutes),
    restricted to roads a truck may legally use at that hour."""
    if tb is not None:
        G = truck_graph(G, tb)
        if o not in G or d not in G or not nx.has_path(G, o, d):
            return []          # no legal route: caller must report "no_legal_route", never fall back
    cands = []
    gen = nx.shortest_simple_paths(G, o, d, weight="time_min")
    for _ in range(k_fast):
        p = next(gen, None)
        if p is None:
            break
        cands.append(tuple(p))
    rr = rates.rate.values
    med = float(np.median(rr))
    for a in alphas:
        w = lambda u, v, data, a=a: data["time_min"] + a * rr[data["edge_id"]] / med * data["length_km"]
        cands.append(tuple(nx.shortest_path(G, o, d, weight=w)))
    return list(dict.fromkeys(cands))


def pareto(options):
    keep = []
    R = [decision_risk(o) for o in options]
    for i, a in enumerate(options):
        dominated = any((b["time_min"] <= a["time_min"] and R[j] <= R[i] and (b["time_min"] < a["time_min"] or R[j] < R[i]))
                        for j, b in enumerate(options) if j != i)
        keep.append(not dominated)
    return keep


def recommend(options, max_extra_time_pct=12.0, min_risk_cut_pct=15.0, p_required=0.9):
    """Fleet policy -> ONE explicit decision object; API, demo and evaluation all display it directly.

    decision: "switch" | "keep" | "defer" | "no_legal_route"
      * qualifying alternative: Pareto-optimal, <= max_extra_time_pct slower, and its decision risk
        (80th-percentile of paired draws when available) >= min_risk_cut_pct below the fastest route's
      * qualifying alternatives are checked in policy-value order; the FIRST whose paired probability
        P(alternative risk < fastest risk) >= p_required is chosen (all are checked before deferring)
      * none passes -> "defer": keep fastest, show the best-evidenced alternative as `considered`
    """
    if not options:
        return dict(decision="no_legal_route", fastest=None, considered=None, chosen=None, p_safer=None, n_qualifying=0)
    fastest = min(options, key=lambda o: o["time_min"])
    qual = []
    for o, is_p in zip(options, pareto(options)):
        if not is_p or o is fastest or list(o["eids"]) == list(fastest["eids"]):
            continue
        dt = (o["time_min"] - fastest["time_min"]) / fastest["time_min"] * 100
        dr = (decision_risk(fastest) - decision_risk(o)) / decision_risk(fastest) * 100
        if dt <= max_extra_time_pct and dr >= min_risk_cut_pct:
            qual.append((dr / max(dt, 0.5), o))
    qual.sort(key=lambda t: -t[0])
    if not qual:
        return dict(decision="keep", fastest=fastest, considered=None, chosen=fastest, p_safer=None, n_qualifying=0)
    if fastest.get("draws") is None or any(o.get("draws") is None for _, o in qual):
        o = qual[0][1]
        return dict(decision="switch", fastest=fastest, considered=o, chosen=o, p_safer=None, n_qualifying=len(qual))
    ps = [(float(np.mean(o["draws"] < fastest["draws"])), o) for _, o in qual]
    for p, o in ps:
        if p >= p_required:
            return dict(decision="switch", fastest=fastest, considered=o, chosen=o, p_safer=p, n_qualifying=len(qual))
    p, o = max(ps, key=lambda t: t[0])
    return dict(decision="defer", fastest=fastest, considered=o, chosen=fastest, p_safer=p, n_qualifying=len(qual))


def decision_is_consistent(R):
    """Integrity rule: a switch must show a route different from the fastest; keep/defer must assign the fastest."""
    if R["decision"] == "no_legal_route":
        return R["chosen"] is None
    same = list(R["chosen"]["eids"]) == list(R["fastest"]["eids"])
    return (not same) if R["decision"] == "switch" else same
