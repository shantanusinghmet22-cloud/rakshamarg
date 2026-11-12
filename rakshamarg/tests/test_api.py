"""API tests (portable: serves from the model export, no retraining).  python tests/test_api.py"""
import importlib, json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT); os.chdir(ROOT)
os.environ["RAKSHAMARG_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
from fastapi.testclient import TestClient
import api
c = TestClient(api.app)
assert c.get("/health").json()["status"] == "ok"
# 1) exact parity with the archived Python reference: decisions and all three route lists, every trip
ref = json.load(open("tests/fixtures/parity_reference.json")); bad = 0; t0 = time.time()
for tr in ref["trips"]:
    tb, w = tr["ctx"].split("/"); R, _ = api.decide(tr["o"], tr["d"], tb, w)
    ids = lambda x: None if x is None else [int(e) for e in x["eids"]]
    bad += not (R["decision"] == tr["decision"] and ids(R["chosen"]) == tr["chosen"] and ids(R["fastest"]) == tr["fastest"] and ids(R["considered"]) == tr["considered"])
assert bad == 0, f"{bad} reference trips differ"; ms = (time.time() - t0) / len(ref["trips"]) * 1000
# 2) saved showcase cases
cases = json.load(open("outputs/dispatch_cases.json"))
for k, v in cases.items():
    tb, w = v["context"].split("/")
    j = c.post("/v1/route-risk", json=dict(origin=v["origin"], destination=v["destination"], time_bucket=tb, weather=w)).json()
    assert j["decision"] == v["decision"] and j["chosen"]["segment_ids"] == v["chosen"]["eids"], k
# 3) review workflow, idempotent assignment, outcome, persistence across a restart
v = cases["typical_defer"]; tb, w = v["context"].split("/")
s = c.post("/v1/route-risk", json=dict(origin=v["origin"], destination=v["destination"], time_bucket=tb, weather=w)).json()
assert s["state"] == "review_required" and s["chosen"] == s["fastest"]
t1 = c.post("/v1/assignments", json={"decision_id": s["decision_id"]}).json(); t2 = c.post("/v1/assignments", json={"decision_id": s["decision_id"]}).json()
assert t1["trip_id"] == t2["trip_id"] and t1["status"] == "pending_review" and t1["assigned_route"] is None
assert c.post(f"/v1/trips/{t1['trip_id']}/outcome", json={"crashes": 0}).status_code == 409          # no route yet
assert [p["trip_id"] for p in c.get("/v1/reviews/pending").json()] == [t1["trip_id"]]
r = c.post(f"/v1/assignments/{t1['trip_id']}/review", json={"supervisor": "Duty supervisor", "choice": "alternative", "note": "fog advisory"}).json()
assert r["status"] == "assigned" and r["assigned"] == "recommended" and r["assigned_route"]["segment_ids"] == s["considered"]["segment_ids"]
assert r["driver_brief"].startswith("Take the recommended route") and t1["driver_brief"] is None      # brief issued only after review
importlib.reload(api); c = TestClient(api.app)                                                          # restart: state comes from SQLite
o = c.post(f"/v1/trips/{t1['trip_id']}/outcome", json={"crashes": 1, "near_misses": 3}).json()
assert o["outcome"]["flag"].startswith(("excess", "no excess")) and o["supervisor"] == "Duty supervisor"
# 4) no-route causes and validation
nl = next(t for t in ref["trips"] if t["decision"] == "no_legal_route"); tb, w = nl["ctx"].split("/")
j = c.post("/v1/route-risk", json=dict(origin=list(map(int, nl["o"].split(","))), destination=list(map(int, nl["d"].split(","))), time_bucket=tb, weather=w)).json()
assert j["state"] == "blocked_by_restrictions" and c.post("/v1/assignments", json={"decision_id": j["decision_id"]}).status_code == 409
assert c.post("/v1/route-risk", json=dict(origin=[0, 0], destination=[0, 0])).status_code == 422
assert c.post("/v1/route-risk", json=dict(origin=[0, 0], destination=[5, 5], weather="snow")).status_code == 422
print(json.dumps(dict(reference_trips_exact=len(ref["trips"]), ms_per_decision=round(ms, 1), restart_persistence="ok", review_workflow="ok")))
print("API TESTS PASSED")
