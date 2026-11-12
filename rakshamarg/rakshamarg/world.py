"""
world.py - Synthetic-but-realistic Indian fleet region used to validate RakshaMarg.

Why synthetic?  Real fleet telematics (harsh-brake / near-miss / crash events with GPS)
is proprietary and not public in India.  To validate the method honestly we build a
simulated region whose *ground-truth* crash risk is known, generate fleet trips and
telematics events from it, and then check whether the pipeline recovers that truth
from noisy, partial observations.  Every assumption is a parameter in CONFIG below.
In the prototype phase the same pipeline ingests OpenStreetMap roads, Open-Meteo
weather, MoRTH black-spot lists and fleet event logs instead (see README).

Region layout (approx. 42 km x 26 km):
  * NH corridor (east-west)      - fast, straight, median openings, mostly unlit
  * SH corridor (north-south)    - medium speed
  * Urban core (south-west)      - dense junctions, market zones, lit
  * Ghat section (north-east)    - sharp curves, steep gradient, unlit
  * District roads elsewhere
  * every segment has unobserved heterogeneity (driveway access, surface quality,
    roadside activity) - the standard over-dispersion seen in crash data, and
  * ~8% of segments carry a *hidden hazard* (cattle crossing, pothole cluster,
    wrong-side traffic near a dhaba) that is NOT in any map attribute - only
    detectable through telematics.  This is what makes fleet data valuable.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import networkx as nx

CONFIG = dict(
    seed=7,
    nx=22, ny=14, spacing_km=2.0,
    trips_per_day=900,
    n_od_pairs=260,
    base_crash_rate=6e-6,            # crashes per veh-km, day/clear, reference road (rare: ~1 crash per 50 near-misses)
    hidden_hazard_share=0.08,
    unobserved_heterogeneity_sd=0.5,
    surrogate_fidelity="faithful",    # "faithful": braking tracks crash risk closely; "noisy": half of braking is stop-go congestion  # log-scale; standard over-dispersion in crash models
    gps_noise_m=12.0,
    corrupt_share=0.02,
    year=2025,
)

SPEED = {"NH": 65, "SH": 50, "MDR": 38, "URBAN": 22, "GHAT": 28}   # effective truck km/h
CLASS_EFFECT = {"NH": 0.30, "SH": 0.15, "MDR": 0.0, "URBAN": 0.20, "GHAT": 0.20}
TIME_BUCKETS = ["day", "evening", "night"]           # 06-18, 18-22, 22-06
TB_HOURS = {"day": (6, 18), "evening": (18, 22), "night": (22, 30)}
TB_SHARE = np.array([0.55, 0.20, 0.25])
WEATHERS = ["clear", "rain", "fog"]
EVENT_TYPES = ["harsh_brake", "harsh_turn", "harsh_accel", "near_miss", "crash"]


def _road_class(i, j):
    if j == 7:
        return "NH"
    if i == 10:
        return "SH"
    if 2 <= i <= 7 and 1 <= j <= 5:
        return "URBAN"
    if 14 <= i <= 19 and 9 <= j <= 13:
        return "GHAT"
    return "MDR"


def build_network(rng):
    c = CONFIG
    G = nx.Graph()
    for i in range(c["nx"]):
        for j in range(c["ny"]):
            G.add_node((i, j), x=i * c["spacing_km"] + rng.normal(0, 0.35),
                       y=j * c["spacing_km"] + rng.normal(0, 0.35))
    rows = []
    for i in range(c["nx"]):
        for j in range(c["ny"]):
            for di, dj in ((1, 0), (0, 1)):
                a, b = (i, j), (i + di, j + dj)
                if b not in G:
                    continue
                # class of the segment: corridor membership wins
                if dj == 0 and j == 7:
                    cls = "NH"
                elif di == 0 and i == 10:
                    cls = "SH"
                else:
                    ca, cb = _road_class(*a), _road_class(*b)
                    cls = ca if ca == cb and ca in ("URBAN", "GHAT") else (
                        "URBAN" if "URBAN" in (ca, cb) else ("GHAT" if "GHAT" in (ca, cb) else "MDR"))
                # thin out district roads a bit to make routing non-trivial
                if cls == "MDR" and rng.random() < 0.12:
                    continue
                G.add_edge(a, b)
                rows.append((a, b, cls))
    # keep largest component
    big = max(nx.connected_components(G), key=len)
    G = G.subgraph(big).copy()

    edges = []
    for a, b, cls in rows:
        if not G.has_edge(a, b):
            continue
        xa, ya, xb, yb = G.nodes[a]["x"], G.nodes[a]["y"], G.nodes[b]["x"], G.nodes[b]["y"]
        straight = float(np.hypot(xb - xa, yb - ya))
        sinuosity = {"GHAT": rng.uniform(1.35, 1.7), "MDR": rng.uniform(1.05, 1.2)}.get(cls, rng.uniform(1.0, 1.06))
        curv = {"NH": rng.uniform(0, 8), "SH": rng.uniform(2, 20), "MDR": rng.uniform(5, 40),
                "URBAN": rng.uniform(5, 25), "GHAT": rng.uniform(90, 220)}[cls]
        junc = {"NH": rng.uniform(0.2, 0.8), "SH": rng.uniform(0.5, 1.5), "MDR": rng.uniform(0.5, 1.5),
                "URBAN": rng.uniform(3, 6), "GHAT": rng.uniform(0.1, 0.5)}[cls]
        median = {"NH": rng.uniform(0.5, 3.0), "SH": rng.uniform(0.2, 1.0)}.get(cls, 0.0)
        lit_p = {"NH": 0.3, "SH": 0.3, "MDR": 0.15, "URBAN": 0.9, "GHAT": 0.05}[cls]
        grad = {"GHAT": rng.uniform(4, 8)}.get(cls, rng.uniform(0, 1.5))
        edges.append(dict(u=a, v=b, cls=cls, length_km=straight * sinuosity,
                          x1=xa, y1=ya, x2=xb, y2=yb,
                          curvature_deg_km=curv, junctions_per_km=junc,
                          median_openings_per_km=median, lit=int(rng.random() < lit_p),
                          gradient_pct=grad,
                          market_zone=int(cls == "URBAN" and rng.random() < 0.3)))
    E = pd.DataFrame(edges)
    E["edge_id"] = np.arange(len(E))
    E["speed_kmph"] = E["cls"].map(SPEED)
    E["time_min"] = E["length_km"] / E["speed_kmph"] * 60
    # hidden hazard: not visible in any attribute
    hid = rng.random(len(E)) < CONFIG["hidden_hazard_share"]
    E["hidden_mult"] = np.where(hid, rng.lognormal(np.log(3.0), 0.35, len(E)), 1.0)
    # ground-truth relative risk (day, clear)
    lr = (0.012 * E.curvature_deg_km + 0.25 * E.junctions_per_km + 0.35 * E.median_openings_per_km
          + 0.08 * E.gradient_pct + 0.4 * E.market_zone + E.cls.map(CLASS_EFFECT) + np.log(E.hidden_mult)
          + rng.normal(0, CONFIG["unobserved_heterogeneity_sd"], len(E)))   # local factors no map captures
    E["true_rel_risk"] = np.exp(lr)
    # public black-spot list (incomplete, lagging): flags ~70% of the truly worst 4%
    thr = E.true_rel_risk.quantile(0.96)
    E["public_blackspot"] = ((E.true_rel_risk >= thr) & (rng.random(len(E)) < 0.7)).astype(int)
    # Indian city truck no-entry windows: market-zone streets closed to HCVs 06:00-22:00
    E["truck_no_entry_day"] = ((E.cls == "URBAN") & (E.market_zone == 1)).astype(int)
    for (a, b), r in zip(zip(E.u, E.v), E.itertuples()):
        G.edges[a, b]["edge_id"] = r.edge_id
        G.edges[a, b]["time_min"] = r.time_min
        G.edges[a, b]["length_km"] = r.length_km
        G.edges[a, b]["no_entry_day"] = bool(r.truck_no_entry_day)
    return G, E


def context_multiplier(E: pd.DataFrame, tb: str, weather: str) -> np.ndarray:
    """Ground-truth time-of-day x lighting x weather multiplier per edge."""
    m = np.ones(len(E))
    m *= {"day": 1.0, "evening": 1.4, "night": 1.9}[tb]
    if tb != "day":
        m *= np.where(E.lit.values == 0, 1.7, 1.0)
    if weather == "rain":
        m *= 1.5 * np.where(E.curvature_deg_km.values > 60, 1.4, 1.0)
    elif weather == "fog":
        fast = E.cls.isin(["NH", "SH"]).values
        m *= np.where(fast, 2.3 if tb != "day" else 1.3, 1.4 if tb != "day" else 1.1)
    return m


def daily_weather(rng, year):
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    w = []
    for d in days:
        p_rain = 0.45 if d.month in (6, 7, 8, 9) else 0.05
        p_fog = 0.35 if d.month in (12, 1) else (0.1 if d.month in (11, 2) else 0.0)
        u = rng.random()
        w.append("rain" if u < p_rain else ("fog" if u < p_rain + p_fog else "clear"))
    return pd.DataFrame({"date": days, "weather": w})


def simulate(seed=None, fidelity=None):
    c = dict(CONFIG)
    if fidelity:
        c["surrogate_fidelity"] = fidelity
    rng = np.random.default_rng(c["seed"] if seed is None else seed)
    G, E = build_network(rng)
    nodes = list(G.nodes)
    W = daily_weather(rng, c["year"])
    W["month"] = W.date.dt.month

    # ---- OD demand and dispatcher routes (fastest + 2nd fastest) ----
    od, paths, shares = [], [], []
    west = [n for n in nodes if n[0] <= 2]
    east = [n for n in nodes if n[0] >= 19]
    while len(od) < c["n_od_pairs"]:
        if rng.random() < 0.3:
            a, b = west[rng.integers(len(west))], east[rng.integers(len(east))]
        else:
            a, b = nodes[rng.integers(len(nodes))], nodes[rng.integers(len(nodes))]
        if a == b or np.hypot(a[0] - b[0], a[1] - b[1]) < 4:
            continue
        gen = nx.shortest_simple_paths(G, a, b, weight="time_min")
        p1 = next(gen)
        p2 = next(gen, p1)
        w = rng.lognormal(0, 0.8)
        for p, s in ((p1, 0.8), (p2, 0.2)):
            od.append((a, b)); paths.append(p); shares.append(w * s)
    shares = np.array(shares) / sum(shares)
    inc = np.zeros((len(paths), len(E)))
    for k, p in enumerate(paths):
        for a, b in zip(p[:-1], p[1:]):
            eid = G.edges[a, b]["edge_id"]
            inc[k, eid] = E.length_km.values[eid]

    # ---- exposure & events per (month, weather, time-bucket, edge) ----
    rates_rel_base = E.true_rel_risk.values
    ev_noise = {t: rng.lognormal(0, s, len(E)) for t, s in
                (("harsh_brake", .35), ("harsh_turn", .3), ("harsh_accel", .4), ("near_miss", .3))}
    congestion = rng.lognormal(0, 0.6, len(E))          # stop-go traffic, unrelated to crash risk
    if c["surrogate_fidelity"] == "noisy":
        ev_noise["near_miss"] = rng.lognormal(0, 0.6, len(E))
    cells, event_rows = [], []
    for (m, w), g in W.groupby(["month", "weather"]):
        ndays = len(g)
        for ti, tb in enumerate(TIME_BUCKETS):
            trips = rng.poisson(c["trips_per_day"] * ndays * TB_SHARE[ti] * shares)
            expo = trips @ inc                                    # veh-km per edge
            rel = rates_rel_base * context_multiplier(E, tb, w)
            lam = {
                "crash": c["base_crash_rate"] * rel,
                "near_miss": 3e-4 * rel * ev_noise["near_miss"],
                "harsh_brake": 4e-3 * ev_noise["harsh_brake"] * (rel ** 0.9 if c["surrogate_fidelity"] == "faithful" else
                               0.5 * rel ** 0.9 + 0.5 * (1 + E.junctions_per_km.values) * congestion),
                "harsh_turn": 1.5e-3 * (1 + E.curvature_deg_km.values / 40) * rel ** 0.4 * ev_noise["harsh_turn"],
                "harsh_accel": 1.2e-3 * (1 + E.junctions_per_km.values) * ev_noise["harsh_accel"],
            }
            cnt = {t: rng.poisson(expo * lam[t]) for t in EVENT_TYPES}
            cells.append(pd.DataFrame(dict(edge_id=E.edge_id, month=m, weather=w, tb=tb, exposure_vkm=expo,
                                           true_crash_rate=lam["crash"], **{f"n_{t}": cnt[t] for t in EVENT_TYPES})))
            dates = g.date.values
            for t in EVENT_TYPES:
                n = cnt[t]
                if n.sum() == 0:
                    continue
                eids = np.repeat(E.edge_id.values, n)
                event_rows.append(pd.DataFrame(dict(true_edge=eids, event_type=t, tb=tb, weather=w,
                                                    date=dates[rng.integers(len(dates), size=len(eids))])))
    cells = pd.concat(cells, ignore_index=True)
    ev = pd.concat(event_rows, ignore_index=True)

    # positions along edge + GPS noise, timestamps, vehicles/drivers
    f = rng.random(len(ev))
    e = E.set_index("edge_id").loc[ev.true_edge]
    noise = c["gps_noise_m"] / 1000
    ev["x_km"] = e.x1.values + f * (e.x2.values - e.x1.values) + rng.normal(0, noise, len(ev))
    ev["y_km"] = e.y1.values + f * (e.y2.values - e.y1.values) + rng.normal(0, noise, len(ev))
    lo, hi = np.array([TB_HOURS[t] for t in ev.tb]).T
    hrs = lo + rng.random(len(ev)) * (hi - lo)
    ev["timestamp"] = pd.to_datetime(ev.date) + pd.to_timedelta(hrs, unit="h")
    ev["speed_kmph"] = np.clip(e.speed_kmph.values * rng.normal(1.0, 0.18, len(ev)), 5, None)
    cohort = rng.choice(["<2 yrs", "2-5 yrs", ">5 yrs"], p=[0.38, 0.35, 0.27], size=len(ev))
    ev["driver_cohort"] = cohort
    # deterministic IDs (no Python hash(), which is salted per process)
    ev["driver_id"] = pd.Series(cohort).map({"<2 yrs": "A", "2-5 yrs": "B", ">5 yrs": "C"}).values + \
        pd.Series(rng.integers(0, 140, len(ev))).astype(str).str.zfill(3).values
    ev["vehicle_id"] = "TRK" + pd.Series(rng.integers(1000, 2200, len(ev))).astype(str)
    ev = ev.drop(columns=["date"])

    # inject realistic data-quality problems
    n_bad = int(c["corrupt_share"] * len(ev))
    dup = ev.sample(n_bad // 2, random_state=1)
    bad = ev.sample(n_bad // 2, random_state=2).copy()
    half = len(bad) // 2
    bad.iloc[:half, bad.columns.get_loc("x_km")] = 0.0
    bad.iloc[:half, bad.columns.get_loc("y_km")] = 0.0           # "null island"
    bad.iloc[half:, bad.columns.get_loc("speed_kmph")] = 240.0   # impossible speed spike
    ev["is_injected_bad"] = 0
    dup["is_injected_bad"] = 1
    bad["is_injected_bad"] = 1
    ev = pd.concat([ev, dup, bad], ignore_index=True).sample(frac=1, random_state=3).reset_index(drop=True)
    ev.insert(0, "event_id", np.arange(len(ev)))
    return dict(G=G, edges=E, cells=cells, events=ev, weather=W, od_paths=paths)
