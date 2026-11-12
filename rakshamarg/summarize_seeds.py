"""summarize_seeds.py - robustness of results across simulated worlds (seeds x surrogate fidelity)."""
import json, glob, os, sys
import numpy as np
SUITE = sys.argv[1] if len(sys.argv) > 1 else "seeds"          # "seeds" (development/robustness) or "holdout"
STEM = {"seeds": ("multiseed_summary", "MULTISEED"), "holdout": ("holdout_summary", "HOLDOUT")}[SUITE]
rows = {}
for f in sorted(glob.glob(f"outputs/{SUITE}/*/metrics.json")):
    M = json.load(open(f)); rows[os.path.basename(os.path.dirname(f))] = M
shas = sorted({m.get("source_sha256_12") for m in rows.values()})
assert len(shas) == 1 and shas[0], f"runs come from different source versions: {shas}"
segs = [m["world"]["segments"] for m in rows.values()]
dfr = [m["evaluation_routes"]["deferral_analysis"] for m in rows.values()]
nd = sum(d["n_defer"] for d in dfr)
out = {"runs": list(rows), "source_sha256_12": shas[0], "dispatch_scorer": next(iter(rows.values()))["dispatch_scorer"],
       "note": {"seeds": "development and robustness suite: these seeds (7, 11, 23, 42, 101) informed development across v0.1-v0.3",
                "holdout": "true holdout: seeds 202-606 were first run after the v0.3 method was frozen (fingerprint unchanged)"}[SUITE],
       "segments_range": [min(segs), max(segs)],
       "integrity": dict(decisions_checked=sum(m["integrity"]["decisions_checked"] for m in rows.values()),
                         inconsistent=sum(m["integrity"]["inconsistent"] for m in rows.values())),
       "no_legal_route_trips_dispatch": sum(m["evaluation_routes"]["no_legal_route_trips"].get("RakshaMarg + braking blend", 0) for m in rows.values()),
       "deferral_all_worlds": dict(trips=sum(d["n_trips"] for d in dfr), defers=nd, switches=sum(d["n_switch"] for d in dfr),
                                   deferred_alternatives_truly_safer_pct=round(sum((d["deferred_alternatives_truly_safer_pct"] or 0) / 100 * d["n_defer"] for d in dfr) / max(nd, 1) * 100, 1))}
for fid in ("faithful", "noisy"):
    Ms = [m for m in rows.values() if m["surrogate_fidelity"] == fid]
    if not Ms:
        continue
    seg = {}
    for meth in Ms[0]["evaluation_segments"]:
        seg[meth] = {k: [m["evaluation_segments"][meth][k] for m in Ms] for k in Ms[0]["evaluation_segments"][meth]}
    rt = {}
    for meth in Ms[0]["evaluation_routes"]["true_risk_reduction_at_fleet_extra_time"]["+2%"]:
        rt[meth] = {b: [m["evaluation_routes"]["true_risk_reduction_at_fleet_extra_time"][b][meth] for m in Ms] for b in ("+1%", "+2%", "+4%")}
    pol = {meth: {k: [m["evaluation_routes"][meth][k] for m in Ms] for k in ("true_risk_reduction_pct", "extra_travel_time_pct", "switches_truly_safer_pct", "deferred_pct")}
           for meth in ("RakshaMarg", "RakshaMarg + braking blend", "Harsh brakes per veh-km", "Crash history", "Road features only")}
    DS = "RakshaMarg + braking blend"
    cov = [m["evaluation_routes"]["band90_coverage_by_scorer"][DS]["overall"] for m in Ms]
    covc = {c: [m["evaluation_routes"]["band90_coverage_by_scorer"][DS]["by_context"][c] for m in Ms] for c in Ms[0]["evaluation_routes"]["band90_coverage_by_scorer"][DS]["by_context"]}
    covm = [m["evaluation_routes"]["band90_coverage_by_scorer"]["RakshaMarg"]["overall"] for m in Ms]
    ms = lambda v: dict(mean=round(float(np.mean([x for x in v if x is not None])), 3), sd=round(float(np.std([x for x in v if x is not None])), 3),
                        min=round(float(np.min([x for x in v if x is not None])), 3), max=round(float(np.max([x for x in v if x is not None])), 3))
    out[fid] = dict(n_worlds=len(Ms),
                    segments={k: {kk: ms(vv) for kk, vv in v.items()} for k, v in seg.items()},
                    matched_budget={k: {kk: ms(vv) for kk, vv in v.items()} for k, v in rt.items()},
                    policy={k: {kk: ms(vv) for kk, vv in v.items()} for k, v in pol.items()},
                    band90_coverage=ms(cov), band90_coverage_by_context={k: ms(v) for k, v in covc.items()},
                    band90_coverage_model_only=ms(covm),
                    deferral={k: ms([m["evaluation_routes"]["deferral_analysis"][k] for m in Ms]) for k in ("n_defer", "n_switch")})
json.dump(out, open(f"outputs/{STEM[0]}.json", "w"), indent=1)
L = [{"seeds": "# Development / robustness suite", "holdout": "# Holdout: worlds first run after the method was frozen"}[SUITE], "", f"Source version {out['source_sha256_12']} for every run. Dispatch scorer: {out['dispatch_scorer']}.",
     out["note"] + ".", f"Segments per world: {out['segments_range'][0]}-{out['segments_range'][1]}. "
     f"Integrity: {out['integrity']['inconsistent']} inconsistent of {out['integrity']['decisions_checked']} decisions. "
     f"Deferrals: {out['deferral_all_worlds']['defers']} of {out['deferral_all_worlds']['trips']} dispatch trips.", ""]
for fid in ("faithful", "noisy"):
    if fid not in out:
        continue
    o = out[fid]
    L += [f"## Surrogate fidelity: {fid} ({o['n_worlds']} worlds)", "", "| Method | Segment ranking | Sparse segments | Segment x context | Top-10% lift |", "|---|---|---|---|---|"]
    for k, v in o["segments"].items():
        L.append(f"| {k} | {v['spearman_segments']['mean']:.3f} ± {v['spearman_segments']['sd']:.3f} | {v['spearman_sparse_segments']['mean']:.3f} | {v['spearman_segment_x_context']['mean']:.3f} | {v['top10pct_lift']['mean']:.2f} |")
    L += ["", "True risk reduction at matched fleet-wide extra travel time (mean ± sd, %):", "", "| Method | +1% time | +2% time | +4% time |", "|---|---|---|---|"]
    for k, v in o["matched_budget"].items():
        L.append(f"| {k} | {v['+1%']['mean']:.1f} ± {v['+1%']['sd']:.1f} | {v['+2%']['mean']:.1f} ± {v['+2%']['sd']:.1f} | {v['+4%']['mean']:.1f} ± {v['+4%']['sd']:.1f} |")
    L += ["", f"90% band coverage (dispatch scorer): {o['band90_coverage']['mean']:.1f}% (min {o['band90_coverage']['min']:.1f}%); by context: " +
          ", ".join(f"{c} {v['mean']:.1f}% (min {v['min']:.1f}%)" for c, v in o["band90_coverage_by_context"].items()), ""]
open(f"outputs/{STEM[1]}.md", "w").write("\n".join(L))
print("\n".join(L))
