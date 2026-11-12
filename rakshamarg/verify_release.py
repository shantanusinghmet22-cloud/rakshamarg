"""verify_release.py - check that every saved result was produced by exactly this source code."""
import glob, hashlib, json, os, sys
SRC = sorted(glob.glob("rakshamarg/*.py")) + ["run_demo.py", "figures.py"]
sha = hashlib.sha256(b"".join(open(f, "rb").read() for f in SRC)).hexdigest()[:12]
files = ["outputs/metrics.json"] + sorted(glob.glob("outputs/seeds/*/metrics.json")) + sorted(glob.glob("outputs/holdout/*/metrics.json"))
bad = [f for f in files if json.load(open(f)).get("source_sha256_12") != sha]
summ = json.load(open("outputs/multiseed_summary.json")).get("source_sha256_12")
if os.path.exists("outputs/holdout_summary.json") and json.load(open("outputs/holdout_summary.json")).get("source_sha256_12") != summ:
    summ = "holdout summary mismatch"
cases = {c.get("scorer") for c in json.load(open("outputs/dispatch_cases.json")).values()}
ok = not bad and summ == sha and cases == {"RakshaMarg + braking blend"}
print(json.dumps(dict(source_sha256_12=sha, result_files=len(files), mismatched=bad, summary_sha=summ, case_scorers=sorted(cases), ok=ok), indent=1))
sys.exit(0 if ok else 1)
