"""Playwright e2e of docs/index.html (simulated mode): every example's decision label, the supervisor-review
workflow, idempotent logging, outcome recording and the CSV schema. Saves screenshots to outputs/snapshots."""
import sys, json, pathlib
from playwright.sync_api import sync_playwright
ROOT = pathlib.Path(__file__).resolve().parents[1]; URL = (ROOT / "docs/index.html").as_uri()
SHOTS = ROOT / "outputs/snapshots"; SHOTS.mkdir(parents=True, exist_ok=True)
EXPECT = {"typical_switch": "SWITCH", "typical_keep": "KEEP FASTEST", "typical_defer": "REVIEW REQUIRED", "no_legal_route": "BLOCKED BY RESTRICTIONS", "selected_switch": "SWITCH"}
errs, out = [], {}
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1.5)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/cdnjs.cloudflare.com/**", lambda r: r.abort())
    pg.goto(URL); pg.wait_for_timeout(1200)
    for k, lab in EXPECT.items():
        pg.click(f'[data-ex="{k}"]'); pg.wait_for_timeout(300); out[k] = pg.inner_text("#decision .badge")
        assert out[k] == lab, (k, out[k]); pg.screenshot(path=str(SHOTS / f"dispatch_{k}.png"))
    pg.click('[data-ex="typical_defer"]'); pg.click("#d-log"); out["review_btn"] = pg.inner_text("#d-log")
    pg.click('[data-ex="typical_switch"]'); pg.click("#d-log"); out["dup"] = pg.is_disabled("#d-log")          # same decision cannot be logged twice
    pg.click('[data-ex="typical_switch"]'); pg.click("#d-log")                                                   # a repeat journey is a new decision
    out["repeat_trips"] = pg.evaluate("window.RM_APP.getLog().filter(t => t.state === 'switch').length")
    pg.click('nav.tabs button[data-tab="log"]'); pg.wait_for_timeout(200)
    tid = pg.get_attribute("[data-ap]", "data-ap"); pg.fill(f'[data-sv="{tid}"]', "Duty supervisor"); pg.fill(f'[data-sn="{tid}"]', "Accept +4 min, NH fog advisory")
    pg.click(f'[data-ap="{tid}"][data-ch="recommended"]'); pg.wait_for_timeout(200)
    oc = pg.get_attribute("[data-ok]", "data-ok"); pg.fill(f'[data-oc="{oc}"]', "1"); pg.fill(f'[data-on="{oc}"]', "3"); pg.click(f'[data-ok="{oc}"]'); pg.wait_for_timeout(200)
    out["log"] = pg.inner_text("#tab-log table"); pg.screenshot(path=str(SHOTS / "tab_log.png"), full_page=True)
    with pg.expect_download() as dl: pg.click("#lg-csv")
    hdr = open(dl.value.path()).readline(); out["csv_cols"] = len(hdr.split(","))
    for t in ["hotspots", "analytics", "evidence", "how"]:
        pg.click(f'nav.tabs button[data-tab="{t}"]'); pg.wait_for_timeout(300); pg.screenshot(path=str(SHOTS / f"tab_{t}.png"), full_page=True)
    pg.click('nav.tabs button[data-tab="dispatch"]'); pg.click("#mode-real"); pg.wait_for_timeout(300); out["real_offline"] = pg.inner_text("#rmap")[:40]
    b.close()
ok = (not errs and out["review_btn"].startswith("Sent to review") and out["dup"] is True and out["repeat_trips"] == 2 and "Driver brief issued" in out["log"] and "Reviewed by Duty supervisor" in out["log"]
      and ("excess severe events flagged" in out["log"] or "no excess-event flag" in out["log"]) and out["csv_cols"] == 30)
print(json.dumps({k: (v[:70] if isinstance(v, str) else v) for k, v in out.items()}, indent=1)); print("JS errors:", errs)
print("CONSOLE E2E", "PASSED" if ok else "FAILED"); sys.exit(0 if ok else 1)
