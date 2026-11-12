"""
api.py - RakshaMarg dispatch API v1.1 (local prototype; simulated fleet region).

    uvicorn api:app --port 8000        # interactive docs at http://localhost:8000/docs

Serves decisions from the versioned model export (model/rakshamarg_model_v1.json), the same file the browser console
uses, so no retraining happens at start-up and decisions do not depend on the host's numerical libraries.
Workflow: score (POST /v1/route-risk) -> assign (POST /v1/assignments) -> [supervisor review] -> outcome.
Records are stored in SQLite (RAKSHAMARG_DB), so they survive restarts and multiple workers.
"""
import base64, hashlib, json, os, sqlite3, uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import List, Literal, Optional
import numpy as np, pandas as pd, networkx as nx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.stats import poisson
from rakshamarg import pipeline as P

MODEL_PATH = os.environ.get("RAKSHAMARG_MODEL", "model/rakshamarg_model_v1.json")
DB_PATH = os.environ.get("RAKSHAMARG_DB", "outputs/rakshamarg.db")
_raw = open(MODEL_PATH, "rb").read(); MODEL_SHA = hashlib.sha256(_raw).hexdigest()[:12]; D = json.loads(_raw)
_c = {c: i for i, c in enumerate(D["edge_cols"])}
_col = lambda k: [r[_c[k]] for r in D["edges"]]
E = pd.DataFrame({"edge_id": _col("id"), "cls": _col("cls"), "length_km": _col("len"), "time_min": _col("time"), "curvature_deg_km": _col("curv"),
                  "junctions_per_km": _col("junc"), "median_openings_per_km": _col("median"), "lit": _col("lit"), "gradient_pct": _col("grad"),
                  "market_zone": _col("market"), "public_blackspot": _col("blackspot"), "truck_no_entry_day": _col("noentry"),
                  "x1": _col("x1"), "y1": _col("y1"), "x2": _col("x2"), "y2": _col("y2")})
G = nx.Graph()
for n in D["nodes"]: G.add_node(n["id"], x=n["x"], y=n["y"])
for r in E.itertuples(): G.add_edge(D["edges"][r.edge_id][_c["u"]], D["edges"][r.edge_id][_c["v"]], edge_id=r.edge_id, time_min=r.time_min,
                                   length_km=r.length_km, no_entry_day=bool(r.truck_no_entry_day))
HS = pd.DataFrame(D["hotspots"])
app = FastAPI(title="RakshaMarg route-risk API", version="1.1.0",
              description="Prototype on a simulated fleet region. Model-based probabilities are not calibrated on real crashes.")


def db():
    con = sqlite3.connect(DB_PATH); con.row_factory = sqlite3.Row
    con.executescript("""CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY, created_at TEXT, request TEXT, result TEXT, model TEXT);
      CREATE TABLE IF NOT EXISTS trips(trip_id TEXT PRIMARY KEY, decision_id TEXT UNIQUE, created_at TEXT, status TEXT, assigned TEXT,
        supervisor TEXT, review_note TEXT, reviewed_at TEXT, outcome TEXT);""")
    return con
now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
jd = lambda o: json.dumps(o, default=lambda v: v.item() if hasattr(v, "item") else str(v))      # numpy-safe JSON


@lru_cache(maxsize=16)
def _ctx(tb, weather):
    C = D["contexts"][f"{tb}/{weather}"]
    q = np.frombuffer(base64.b64decode(C["mult_b64"]), dtype="<i2").reshape(C["mult_shape"])
    return pd.DataFrame({"edge_id": E.edge_id.values, "rate": np.array(C["rate"])}), np.exp(q / C["mult_q"]), C["ref"]


def decide(o, d, tb, weather, max_extra=12.0, min_cut=15.0, p_required=0.9):
    """Same logic as the browser engine; returns (R, ref). Public for tests."""
    rates, mult, ref = _ctx(tb, weather)
    opts = [P.score_route(P.path_edges(G, list(p)), rates, E, mult=mult) for p in P.candidate_routes(G, o, d, rates, tb=tb)]
    R = P.recommend(opts, max_extra, min_cut, p_required)
    if R["decision"] == "no_legal_route":
        R["cause"] = "blocked_by_restrictions" if nx.has_path(G, o, d) else "network_unreachable"
    if R["p_safer"] is not None:
        S = len(R["fastest"]["draws"]); R["borderline"] = bool(abs(R["p_safer"] - p_required) <= 1.96 * np.sqrt(max(R["p_safer"] * (1 - R["p_safer"]), 1e-4) / S))
    return R, ref


class RouteRequest(BaseModel):
    origin: List[int] = Field(..., min_length=2, max_length=2, examples=[[1, 0]])
    destination: List[int] = Field(..., min_length=2, max_length=2, examples=[[21, 2]])
    time_bucket: Literal["day", "evening", "night"] = "night"
    weather: Literal["clear", "rain", "fog"] = "clear"
    max_extra_time_pct: float = Field(12.0, ge=0, le=100)
    min_risk_cut_pct: float = Field(15.0, ge=0, le=100)
    p_required: float = Field(0.9, ge=0.5, le=0.999)


def _pack(s, ref):
    if s is None:
        return None
    return dict(time_min=round(s["time_min"], 2), km=round(s["length_km"], 2), risk_index=round(P.risk_index(s["expected_crashes_per_1000_trips"], ref)),
                expected_crashes_per_1000_trips=s["expected_crashes_per_1000_trips"], decision_risk_80pct=P.decision_risk(s),
                band90=[s["ci90_low"], s["ci90_high"]], confidence=s["confidence"], segment_ids=[int(e) for e in s["eids"]])


@app.get("/health")
def health():
    return {"status": "ok", "model_export_sha256_12": MODEL_SHA, "training_source_fingerprint": D["meta"]["source_sha256_12"],
            "segments": int(len(E)), "data": "simulated", "store": "sqlite"}


@app.post("/v1/route-risk")
def route_risk(req: RouteRequest):
    o, d = f"{req.origin[0]},{req.origin[1]}", f"{req.destination[0]},{req.destination[1]}"
    if o not in G or d not in G or o == d:
        raise HTTPException(422, "origin/destination must be distinct nodes of the road graph")
    R, ref = decide(o, d, req.time_bucket, req.weather, req.max_extra_time_pct, req.min_risk_cut_pct, req.p_required)
    if not P.decision_is_consistent(R):
        raise HTTPException(500, "internal consistency check failed")
    state = R.get("cause", R["decision"]) if R["decision"] == "no_legal_route" else ("review_required" if R["decision"] == "defer" else R["decision"])
    res = dict(decision=R["decision"], state=state, cause=R.get("cause"), comparison_probability=R["p_safer"], borderline=R.get("borderline", False),
               n_qualifying_alternatives=R["n_qualifying"], fastest=_pack(R["fastest"], ref), considered=_pack(R["considered"], ref), chosen=_pack(R["chosen"], ref),
               reasons_fastest=[] if R["fastest"] is None else P.explain_segments(R["fastest"]["eids"], R["fastest"]["segment_risk"], E, HS, req.time_bucket),
               model_export_sha256_12=MODEL_SHA,
               note="comparison_probability = share of paired model draws in which the alternative has lower expected risk; not calibrated on real crashes")
    did = "D-" + uuid.uuid4().hex[:12]
    with db() as con:
        con.execute("INSERT INTO decisions VALUES (?,?,?,?,?)", (did, now(), req.model_dump_json(), jd(res), MODEL_SHA))
    res = json.loads(jd(res))
    return dict(decision_id=did, **res)


class AssignRequest(BaseModel):
    decision_id: str


@app.post("/v1/assignments")
def assign(a: AssignRequest):
    """Idempotent: assigning the same decision twice returns the same trip."""
    with db() as con:
        row = con.execute("SELECT * FROM decisions WHERE decision_id=?", (a.decision_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown decision_id")
        res = json.loads(row["result"])
        if res["chosen"] is None:
            raise HTTPException(409, f"no route to assign ({res['cause']})")
        old = con.execute("SELECT * FROM trips WHERE decision_id=?", (a.decision_id,)).fetchone()
        if old:
            return _trip(con, old["trip_id"])
        tid, pending = "T-" + uuid.uuid4().hex[:10], res["decision"] == "defer"
        con.execute("INSERT INTO trips VALUES (?,?,?,?,?,?,?,?,?)", (tid, a.decision_id, now(), "pending_review" if pending else "assigned",
                    None if pending else ("recommended" if res["decision"] == "switch" else "fastest"), None, None, None, None))
        return _trip(con, tid)


def _trip(con, tid):
    t = con.execute("SELECT * FROM trips WHERE trip_id=?", (tid,)).fetchone()
    if not t:
        raise HTTPException(404, "unknown trip_id")
    res = json.loads(con.execute("SELECT result FROM decisions WHERE decision_id=?", (t["decision_id"],)).fetchone()["result"])
    route = res["considered"] if t["assigned"] == "recommended" else res["fastest"] if t["assigned"] == "fastest" else None
    req = json.loads(con.execute("SELECT request FROM decisions WHERE decision_id=?", (t["decision_id"],)).fetchone()["request"])
    brief = _brief(route, t["assigned"], req["time_bucket"], req["weather"]) if route else None
    return dict(trip_id=tid, decision_id=t["decision_id"], status=t["status"], decision=res["decision"], assigned=t["assigned"], assigned_route=route, driver_brief=brief,
                supervisor=t["supervisor"], review_note=t["review_note"], reviewed_at=t["reviewed_at"], outcome=json.loads(t["outcome"]) if t["outcome"] else None)


_KEYS = [("sharp curves", "sharp curves"), ("steep gradient", "steep gradients"), ("median openings", "frequent median cuts"), ("dense junctions", "dense junctions"),
         ("unlit", "unlit stretches"), ("market zone", "a market zone"), ("black-spot", "a listed black spot"), ("hotspot", "a fleet hotspot")]


def _brief(route, assigned, tb, weather):
    """English driver-brief template for the assigned route (issued at assignment, or after a supervisor's review)."""
    rates, _, _ = _ctx(tb, weather); eids = route["segment_ids"]
    seg = rates.rate.values[eids] * E.length_km.values[eids] * 1000
    keys = []
    for r in P.explain_segments(eids, seg, E, HS, tb):
        for x in r["reasons"]:
            for k, t in _KEYS:
                if k in x and t not in keys: keys.append(t)
    text = f"Take the {'recommended' if assigned == 'recommended' else 'fastest'} route ({route['km']:.0f} km, about {route['time_min']:.0f} min)."
    if keys: text += " Take extra care at: " + ", ".join(keys[:3]) + "."
    if weather == "fog": text += " In fog: keep a much longer following distance than usual, use low beam and fog lamps, never stop on the carriageway."
    elif weather == "rain": text += " In rain: slow down on curves and avoid hard braking."
    if tb != "day": text += " After dark, watch for unlit stretches and median openings."
    return text + " (Template; to be reviewed by a fleet safety lead.)"


@app.get("/v1/trips/{trip_id}")
def get_trip(trip_id: str):
    with db() as con:
        return _trip(con, trip_id)


@app.get("/v1/reviews/pending")
def pending():
    with db() as con:
        return [_trip(con, r["trip_id"]) for r in con.execute("SELECT trip_id FROM trips WHERE status='pending_review' ORDER BY created_at")]


class Review(BaseModel):
    supervisor: str = Field(..., min_length=1)
    choice: Literal["fastest", "alternative"]
    note: str = ""


@app.post("/v1/assignments/{trip_id}/review")
def review(trip_id: str, r: Review):
    with db() as con:
        t = _trip(con, trip_id)
        if t["status"] != "pending_review":
            raise HTTPException(409, "trip is not awaiting review")
        con.execute("UPDATE trips SET status='assigned', assigned=?, supervisor=?, review_note=?, reviewed_at=? WHERE trip_id=?",
                    ("recommended" if r.choice == "alternative" else "fastest", r.supervisor, r.note, now(), trip_id))
        return _trip(con, trip_id)


class Outcome(BaseModel):
    crashes: int = Field(0, ge=0)
    near_misses: int = Field(0, ge=0)
    harsh_brakes: Optional[int] = Field(None, ge=0)


@app.post("/v1/trips/{trip_id}/outcome")
def outcome(trip_id: str, out: Outcome):
    """Monitoring flag: are observed severe events (crashes + near-misses) unusually high for the assigned route?"""
    with db() as con:
        t = _trip(con, trip_id)
        if t["status"] != "assigned":
            raise HTTPException(409, "trip has no assigned route yet")
        exp_severe = t["assigned_route"]["expected_crashes_per_1000_trips"] / 1000 / D["meta"]["model_crash_scale"]
        obs = out.crashes + out.near_misses; p = float(poisson.sf(obs - 1, exp_severe)) if obs > 0 else 1.0
        rec = dict(out.model_dump(), expected_severe_events=exp_severe, observed_severe_events=obs, p_value_observed_or_more=p, recorded_at=now(),
                   flag="excess severe events flagged: review route" if p < 0.05 else "no excess-event flag (monitoring only; not a model validation)")
        con.execute("UPDATE trips SET outcome=? WHERE trip_id=?", (jd(rec), trip_id))
        return _trip(con, trip_id)


@app.get("/v1/hotspots")
def hotspots(road_class: Optional[str] = None, top: int = 10, min_night_share: float = 0.0, public_blackspot: Optional[bool] = None):
    h = HS.copy()
    if road_class: h = h[h.road_class.str.upper() == road_class.upper()]
    if public_blackspot is not None: h = h[h.public_blackspot == int(public_blackspot)]
    return h[h.night_share >= min_night_share].head(max(1, min(top, 100))).to_dict(orient="records")


@app.get("/v1/routes/high-risk")
def high_risk(min_risk_index: int = 70, top: int = 20):
    with db() as con:
        trips = [_trip(con, r["trip_id"]) for r in con.execute("SELECT trip_id FROM trips WHERE status='assigned'")]
    trips = [t for t in trips if t["assigned_route"]["risk_index"] >= min_risk_index]
    return sorted(trips, key=lambda t: -t["assigned_route"]["risk_index"])[:max(1, min(top, 200))]
