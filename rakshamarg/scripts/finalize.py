"""scripts/finalize.py - turn a saved real OSM snapshot (from the console's "Download dated snapshot") and the public
links into the final release.  python scripts/finalize.py --snapshot nh19_osm_snapshot.json --links links.json
links.json: {"demo_url": "...", "repo_url": "...", "video_url": "..."}  (only real, working URLs)"""
import argparse, json, os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT)
ap = argparse.ArgumentParser(); ap.add_argument("--snapshot"); ap.add_argument("--links"); a = ap.parse_args()
os.makedirs("outputs/test_results", exist_ok=True)
if a.snapshot:
    rep = subprocess.run(["node", "tests/verify_snapshot.cjs", a.snapshot], capture_output=True, text=True)
    open("outputs/test_results/real_snapshot_report.json", "w").write(rep.stdout)
    if rep.returncode != 0: sys.exit("snapshot verification FAILED - see outputs/test_results/real_snapshot_report.json")
    base = json.loads(rep.stdout)["osm_base"]
    os.makedirs("docs/data", exist_ok=True); shutil.copy(a.snapshot, "docs/data/nh19_osm_snapshot.json")
    open("docs/data/ATTRIBUTION.md", "w").write(f"nh19_osm_snapshot.json: road data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0, https://www.openstreetmap.org/copyright. Overpass extract, data as of {base}. Bounding box 25.30–25.58 N, 81.55–82.20 E; highway classes motorway–tertiary.\n")
    print("snapshot verified and installed:", base)
if a.links:
    L = json.load(open(a.links)); assert all(u.startswith("https://") for u in L.values()), "links must be https URLs"
    shutil.copy(a.links, "web/links.json"); print("links installed:", L)
subprocess.run([sys.executable, "build_web.py"], check=True)
print("next: python tests/e2e_snapshot.py && python tests/record_demo.py, then rebuild the deck")
