"""Playwright check of the console on the installed real OSM snapshot (docs/data/nh19_osm_snapshot.json); saves real-road screenshots."""
import json, pathlib, sys
from playwright.sync_api import sync_playwright
ROOT = pathlib.Path(__file__).resolve().parents[1]; import sys as _s; _s.path.insert(0, str(ROOT / "tests")); from _serve import serve; URL, _SRV = serve(ROOT / "docs"); LF = ROOT / "tests/vendor/leaflet"; SNAP = ROOT / "docs/data/nh19_osm_snapshot.json"
SHOTS = ROOT / "outputs/snapshots"; SHOTS.mkdir(parents=True, exist_ok=True); errs, out = [], {}
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1.5); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/leaflet.min.js", lambda r: r.fulfill(path=str(LF / "leaflet.js"), content_type="application/javascript"))
    pg.route("**/leaflet.min.css", lambda r: r.fulfill(path=str(LF / "leaflet.css"), content_type="text/css"))
    pg.route("**/tile.openstreetmap.org/**", lambda r: r.abort()); pg.route("**/api.open-meteo.com/**", lambda r: r.abort()); pg.route("**/api/interpreter", lambda r: r.abort())
    pg.goto(URL); pg.wait_for_timeout(600); pg.click("#mode-real"); pg.wait_for_timeout(300); pg.select_option("#r-wx", "clear")
    pg.click("#r-load"); pg.wait_for_selector("#decision .badge", timeout=60000); pg.wait_for_timeout(800)
    out["status"] = pg.inner_text("#r-status"); out["check"] = pg.inner_text("details"); out["preset1"] = pg.inner_text("#decision .badge")
    pg.screenshot(path=str(SHOTS / "real_nh19_preset1.png"))
    pg.click("#r-ex2"); pg.wait_for_timeout(600); out["preset2"] = pg.inner_text("#decision .badge"); pg.screenshot(path=str(SHOTS / "real_nh19_preset2.png"))
    b.close()
print(json.dumps(out, indent=1)); print("JS errors:", errs)
ok = not errs and "saved OpenStreetMap snapshot" in out["status"] and "west→east ✓" in out["check"] and "Jn→Naini ✓" in out["check"] and "NO ROUTE" not in out["preset1"] + out["preset2"]
print("SNAPSHOT E2E", "PASSED" if ok else "FAILED"); sys.exit(0 if ok else 1)
