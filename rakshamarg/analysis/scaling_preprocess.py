"""Supplementary: event-ingestion throughput (cleaning + map-matching) vs event volume (theme task 8)."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from rakshamarg.world import simulate
from rakshamarg import pipeline as P
W = simulate(seed=7); raw, E = W["events"], W["edges"]; out = []
for n in (100_000, 400_000, 1_600_000):
    ev = raw.sample(n, replace=True, random_state=1).reset_index(drop=True); ev["event_id"] = range(n)
    ev["timestamp"] = ev.timestamp + pd.to_timedelta(ev.index % 997, unit="s")   # keep resampled rows distinct
    t = time.time(); _, log = P.preprocess(ev, E); s = time.time() - t
    out.append(dict(events=n, seconds=round(s, 2), events_per_second=int(n / s)))
json.dump(out, open("outputs/supplementary/scaling_ingest.json", "w"), indent=1); print(pd.DataFrame(out).to_string(index=False))
