"""build_web.py - assemble the dispatcher console into ONE self-contained file: docs/index.html (GitHub Pages / offline)."""
import json, os, glob
import numpy as np
os.makedirs("docs/data", exist_ok=True)
BL, RD = "RakshaMarg + braking blend", "Road features only"
cases = json.load(open("outputs/dispatch_cases.json"))
ex = {k: dict(o=f"{v['origin'][0]},{v['origin'][1]}", d=f"{v['destination'][0]},{v['destination'][1]}", ctx=v["context"]) for k, v in cases.items()}
for t in json.load(open("tests/fixtures/parity_reference.json"))["trips"]:
    if t["decision"] == "no_legal_route":
        ex["no_legal_route"] = dict(o=t["o"], d=t["d"], ctx=t["ctx"]); break
par = json.load(open("outputs/test_results/parity_result.json"))            # written by: node tests/test_engine.cjs

def suite(name, summary):
    S, out = json.load(open(summary)), {}
    for f in ("faithful", "noisy"):
        o = S[f]; mb = lambda k: o["matched_budget"][k]["+2%"]
        diffs = [json.load(open(p))["evaluation_routes"]["true_risk_reduction_at_fleet_extra_time"]["+2%"] for p in sorted(glob.glob(f"outputs/{name}/{f}_seed*/metrics.json"))]
        d = np.array([x[BL] - x[RD] for x in diffs])
        out[f] = dict(mb2_blend=mb(BL), mb2_model=mb("RakshaMarg"), mb2_road=mb(RD), mb2_braking=mb("Harsh brakes per veh-km"), mb2_crash=mb("Crash history"),
                      seg_model=o["segments"]["RakshaMarg (full)"]["spearman_segments"], seg_blend=o["segments"][BL]["spearman_segments"],
                      seg_braking=o["segments"]["Harsh brakes per veh-km (smoothed)"]["spearman_segments"],
                      policy_cut=o["policy"][BL]["true_risk_reduction_pct"], policy_time=o["policy"][BL]["extra_travel_time_pct"],
                      safer=o["policy"][BL]["switches_truly_safer_pct"], coverage=o["band90_coverage"],
                      blend_minus_road=dict(mean=float(d.mean()), sd=float(d.std()), per_world=[round(float(v), 2) for v in d], losses=int((d < 0).sum())))
    out["deferral"], out["integrity"] = S["deferral_all_worlds"], S["integrity"]
    return out
evd = dict(holdout=suite("holdout", "outputs/holdout_summary.json"), development=suite("seeds", "outputs/multiseed_summary.json"))
evd["review_cost"] = json.load(open("outputs/supplementary/review_time_cost.json"))
json.dump(evd, open("outputs/test_results/evidence_bundle.json", "w"), indent=1)
html = open("web/index.html").read()
html = html.replace("<!--ENGINE-->", "<script>\n" + open("web/engine.js").read() + "\n</script>")
html = html.replace("<!--DATA-->", "<script>\n" + open("web/data_sim.js").read() + f"window.RM_EXAMPLES={json.dumps(ex)};window.RM_PARITY={json.dumps(par)};window.RM_EVIDENCE={json.dumps(evd)};\n</script>")
links = json.load(open("web/links.json")) if os.path.exists("web/links.json") else {}
html = html.replace("<!--DATA-->", f"<script>window.RM_LINKS={json.dumps(links)};</script><!--DATA-->")
html = html.replace("<!--APP-->", "<script>\n" + open("web/app.js").read() + "\n</script>")
open("docs/index.html", "w").write(html); open("docs/.nojekyll", "w").write("")
h, n = evd["holdout"]["faithful"]["blend_minus_road"], evd["holdout"]["noisy"]["blend_minus_road"]
print(f"docs/index.html {os.path.getsize('docs/index.html')/1e6:.2f} MB | parity {par['decisions_agree']}/{par['trips']} | blend-road holdout faithful {h['per_world']} noisy {n['per_world']}")
