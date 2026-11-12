"""Regression tests for the v0.2 review findings:  python tests/test_pipeline.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd, networkx as nx
from rakshamarg import pipeline as P

# 1) truck rules are never silently dropped
G = nx.Graph()
G.add_edge("A", "B", edge_id=0, time_min=5.0, length_km=2.0, no_entry_day=True)    # only road: closed 06-22 h
rates = pd.DataFrame({"edge_id": [0], "rate": [1e-5]})
assert P.candidate_routes(G, "A", "B", rates, tb="day") == [], "illegal road returned during no-entry window"
assert P.candidate_routes(G, "A", "B", rates, tb="evening") == []
assert P.candidate_routes(G, "A", "B", rates, tb="night") != [], "road should be legal at night"
R = P.recommend([])
assert R["decision"] == "no_legal_route" and R["chosen"] is None and P.decision_is_consistent(R)

# 2) every qualifying alternative is checked before deferring, and the decision object is self-consistent
rng = np.random.default_rng(0)
def opt(eids, t, base, noise):
    d = base * np.exp(noise * rng.standard_normal(4000))
    return dict(eids=eids, time_min=t, expected_crashes_per_1000_trips=base, draws=d, risk_averse=float(np.quantile(d, 0.8)))
fast = opt([1, 2], 60.0, 10.0, 0.05)
alt_weak = opt([3, 4], 61.0, 6.0, 0.5)     # qualifies with the best policy value, but P(safer) ~0.85 < 0.9
alt_strong = opt([5, 6], 64.0, 7.0, 0.05)  # smaller gain, strong evidence
R = P.recommend([fast, alt_weak, alt_strong], max_extra_time_pct=12, min_risk_cut_pct=0, p_required=0.9)
assert R["n_qualifying"] == 2, R["n_qualifying"]
assert R["decision"] == "switch" and R["chosen"] is alt_strong, R["decision"]
assert P.decision_is_consistent(R)
R = P.recommend([fast, alt_weak], max_extra_time_pct=12, min_risk_cut_pct=0, p_required=0.9)
assert R["decision"] == "defer" and R["chosen"] is fast and R["considered"] is alt_weak and P.decision_is_consistent(R)
R = P.recommend([fast], max_extra_time_pct=12)
assert R["decision"] == "keep" and R["considered"] is None and P.decision_is_consistent(R)
# a "switch" can never show the fastest route as the recommendation
bad = dict(decision="switch", fastest=fast, considered=fast, chosen=fast)
assert not P.decision_is_consistent(bad)
print("PIPELINE REGRESSION TESTS PASSED")
