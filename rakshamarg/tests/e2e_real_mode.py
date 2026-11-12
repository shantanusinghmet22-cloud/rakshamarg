"""Playwright e2e of the experimental real-roads mode with Overpass/Open-Meteo-format mock responses.
The fixture reproduces the v1.0 failure (one-way dead-end stubs at the extreme NH ends) plus roundabout,
hgv=no, maxweight and an isolated fragment. Leaflet is vendored in tests/vendor (BSD-2-Clause)."""
import json, math, pathlib, sys
from playwright.sync_api import sync_playwright
ROOT = pathlib.Path(__file__).resolve().parents[1]; URL = (ROOT / "docs/index.html").as_uri(); LF = ROOT / "tests/vendor/leaflet"
els, ids = [], {}
def node(i, lat, lon): els.append({"type": "node", "id": i, "lat": lat, "lon": lon}); return i
nid = 1
for i in range(7):
    for j in range(14):
        ids[i, j] = node(nid, 25.32 + i * 0.04 + 0.004 * math.sin(j), 81.62 + j * 0.04); nid += 1
way = lambda w, nodes, tags: els.append({"type": "way", "id": w, "nodes": nodes, "tags": tags})
w = 1
for i in range(7):
    if i == 3: continue
    way(w, [ids[i, j] for j in range(14)], {"highway": "secondary" if i % 2 else "tertiary"}); w += 1
way(w, [ids[3, j] for j in range(14)], {"highway": "trunk", "ref": "NH19", "oneway": "yes", "lit": "no"}); w += 1            # eastbound carriageway
wb = [node(9000 + j, 25.4415 + 0.004 * math.sin(j), 81.62 + j * 0.04) for j in range(14)]
way(w, wb[::-1], {"highway": "trunk", "ref": "NH19", "oneway": "yes"}); w += 1                                                   # westbound carriageway
way(w, [wb[0], ids[3, 0]], {"highway": "trunk_link", "ref": "NH19"}); w += 1; way(w, [wb[13], ids[3, 13]], {"highway": "trunk_link", "ref": "NH19"}); w += 1
west, east = node(9100, 25.44, 81.57), node(9101, 25.44, 82.17)                                                                 # dead-end one-way stubs
way(w, [ids[3, 0], west], {"highway": "trunk", "ref": "NH19", "oneway": "yes"}); w += 1; way(w, [ids[3, 13], east], {"highway": "trunk", "ref": "NH19", "oneway": "yes"}); w += 1
for j in range(14):
    tags = {"highway": "tertiary" if j % 3 else "primary"}
    if j == 4: tags["hgv"] = "no"
    if j == 7: tags["maxweight"] = "16"
    way(w, [ids[i, j] for i in range(7)], tags); w += 1
rb = [node(9200 + k, 25.36 + 0.003 * math.cos(k), 81.80 + 0.003 * math.sin(k)) for k in range(6)]
way(w, rb + [rb[0]], {"highway": "secondary", "junction": "roundabout"}); w += 1; way(w, [rb[0], ids[1, 5]], {"highway": "secondary"}); w += 1
iso = [node(9300, 25.55, 82.10), node(9301, 25.56, 82.12)]; way(w, iso, {"highway": "tertiary"}); w += 1                          # isolated fragment
overpass = {"version": 0.6, "osm3s": {"timestamp_osm_base": "2026-11-05T10:00:00Z"}, "elements": els}
times = [f"2026-11-{d:02d}T{h:02d}:00" for d in range(1, 30) for h in range(24)]
meteo = {"hourly": {"time": times, "weather_code": [45 if (h < 7 or h >= 22) else 3 for d in range(1, 30) for h in range(24)],
                    "visibility": [300.0 if (h < 7 or h >= 22) else 9000.0 for d in range(1, 30) for h in range(24)], "precipitation": [0.0] * len(times)}}
errs, out = [], {}
badge = lambda pg: pg.inner_text("#decision .badge")
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1600, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/leaflet.min.js", lambda r: r.fulfill(path=str(LF / "leaflet.js"), content_type="application/javascript"))
    pg.route("**/leaflet.min.css", lambda r: r.fulfill(path=str(LF / "leaflet.css"), content_type="text/css"))
    pg.route("**/tile.openstreetmap.org/**", lambda r: r.abort()); pg.route("**/data/nh19_osm_snapshot.json", lambda r: r.fulfill(status=404, body="no"))
    pg.route("**/api/interpreter", lambda r: r.fulfill(body=json.dumps(overpass), content_type="application/json"))
    pg.route("**/api.open-meteo.com/**", lambda r: r.fulfill(body=json.dumps(meteo), content_type="application/json"))
    pg.goto(URL); pg.wait_for_timeout(600); pg.click("#mode-real"); pg.wait_for_timeout(300)
    pg.fill("#r-when", "2026-11-10T14:00"); pg.dispatch_event("#r-when", "change")
    pg.click("#r-load"); pg.wait_for_selector("#decision .badge", timeout=30000); pg.wait_for_timeout(300)
    out["check"] = pg.inner_text("details"); out["preset1"] = badge(pg); out["banner"] = pg.inner_text("#decision .banner")[:45]
    out["provenance"] = "Input provenance" in pg.inner_text("#decision")
    pg.click("#r-ex2"); pg.wait_for_timeout(300); out["preset2"] = badge(pg)
    pg.fill("#r-when", "2027-06-01T10:00"); pg.dispatch_event("#r-when", "change"); pg.wait_for_timeout(500); out["far_future"] = badge(pg)
    pg.select_option("#r-wx", "fog"); pg.wait_for_timeout(400); out["manual_fog"] = badge(pg)
    pg.fill('[data-zr="1"]', "60"); pg.dispatch_event('[data-zr="1"]', "change"); pg.check('[data-z="1"]'); pg.wait_for_timeout(400); out["big_zone"] = badge(pg)
    b.close()
print(json.dumps(out, indent=1)); print("JS errors:", errs)
ok = (not errs and "west→east ✓" in out["check"] and "Jn→Naini ✓" in out["check"] and "NO ROUTE" not in out["preset1"] and "NO ROUTE" not in out["preset2"]
      and out["far_future"] == "WEATHER UNKNOWN" and out["manual_fog"] not in ("WEATHER UNKNOWN",) and out["big_zone"] == "BLOCKED BY RESTRICTIONS" and out["provenance"]
      and "hgv=no: 1" in out["check"] and "Experimental" in out["banner"])
print("REAL-MODE E2E", "PASSED" if ok else "FAILED"); sys.exit(0 if ok else 1)
