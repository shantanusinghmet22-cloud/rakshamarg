"""Record a captioned walkthrough (simulated fleet region) -> outputs/RakshaMarg_demo.mp4.
Every narrated scene first ASSERTS the decision shown on screen; captions are built from on-screen / release values."""
import json, pathlib, re, shutil, subprocess
from playwright.sync_api import sync_playwright
ROOT = pathlib.Path(__file__).resolve().parents[1]; import sys as _s; _s.path.insert(0, str(ROOT / "tests")); from _serve import serve; URL, _SRV = serve(ROOT / "docs"); VD = ROOT / "outputs/video_tmp"
shutil.rmtree(VD, ignore_errors=True)
C = json.load(open(ROOT / "outputs/dispatch_cases.json")); EV = json.load(open(ROOT / "outputs/test_results/evidence_bundle.json"))
PAR = json.load(open(ROOT / "outputs/test_results/parity_result.json")); hf = EV["holdout"]["faithful"]; hn = EV["holdout"]["noisy"]
CAP = """t=>{let c=document.getElementById('cap');if(!c){c=document.createElement('div');c.id='cap';c.style.cssText='position:sticky;top:0;z-index:99999;background:#0F161F;color:#fff;font:600 21px Calibri,Carlito,sans-serif;line-height:1.35;padding:12px 26px;min-height:62px;display:flex;align-items:center';document.body.prepend(c)};c.textContent=t}"""
CARD = """([a,b])=>{let c=document.getElementById('card');if(!c){c=document.createElement('div');c.id='card';c.style.cssText='position:fixed;inset:0;background:#1B2430;color:#fff;z-index:100000;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:Calibri,Carlito,sans-serif;text-align:center;padding:40px';document.body.appendChild(c)};c.style.display=a?'flex':'none';c.innerHTML='<div style=\"font-size:64px;font-weight:700\">Raksha<span style=\"color:#3CC283\">Marg</span></div><div style=\"font-size:28px;color:#F2B53A;margin-top:14px\">'+a+'</div><div style=\"font-size:20px;color:#C9D1DB;margin-top:22px;max-width:1100px\">'+b+'</div>'}"""
scenes = []
with sync_playwright() as p:
    br = p.chromium.launch(); ctx = br.new_context(viewport={"width": 1440, "height": 960}, record_video_dir=str(VD), record_video_size={"width": 1440, "height": 960})
    pg = ctx.new_page(); pg.route("**/cdnjs.cloudflare.com/**", lambda r: r.abort()); pg.goto(URL); pg.wait_for_timeout(1000)
    cap = lambda t, ms: (pg.evaluate(CAP, t), pg.wait_for_timeout(ms), scenes.append(t))
    card = lambda a, b, ms: (pg.evaluate(CARD, [a, b]), pg.wait_for_timeout(ms))
    badge = lambda: pg.inner_text("#decision .badge"); text = lambda: pg.inner_text("#decision")
    def expect(label):
        got = badge(); assert got == label, f"screen shows {got}, script expected {label}"; return got
    pv = lambda: float(re.search(r"P\(lower expected risk\) = ([0-9.]+)", text()).group(1))
    trade = lambda: re.search(r"Trade-off: ([−+])(\d+)% expected crashes \(model\) for \+([0-9.]+) min", text()).groups()
    card("Pre-dispatch route risk decisions for fleet dispatchers", "Prototype v1.1 · Netradyne Campus Innovation Challenge 2026 · Team PLACER, IIT (BHU) Varanasi · this walkthrough uses the simulated fleet region", 4200); card("", "", 150)
    pg.click('[data-ex="typical_switch"]'); expect("SWITCH"); s, cut, mins = trade(); p_ = pv()
    cap(f"A typical trip (simulated region). The alternative has {cut}% lower expected crashes for +{mins} min, and the model-based comparison probability is {p_:.3f} (≥ 0.90), so RakshaMarg says SWITCH.", 7500)
    pg.evaluate("()=>{const s=document.querySelector('#p-mc');s.value=50;s.dispatchEvent(new Event('input'))}"); pg.wait_for_timeout(300); expect("KEEP FASTEST")
    cap(f"The fleet sets the policy. If it demands a 50% risk reduction, the same trip no longer qualifies: KEEP FASTEST.", 6000)
    pg.click('[data-ex="selected_switch"]'); expect("SWITCH"); s, cut2, mins2 = trade()
    cap(f"Selected illustration (the largest gain we found): night, dense fog. The fastest route runs along an unlit NH stretch with median cuts; the alternative has {cut2}% lower expected crashes for +{mins2} min.", 7500)
    pg.select_option("#s-tb", "day"); pg.select_option("#s-w", "clear"); pg.wait_for_timeout(300); b2 = badge()
    if b2 == "SWITCH":
        s, cut3, mins3 = trade(); cap(f"Same trip by day in clear weather: the alternative still meets the policy, but the gain shrinks to {cut3}% for +{mins3} min. Context changes the decision.", 6500)
    else:
        cap(f"Same trip by day in clear weather: the decision becomes {b2}. Context changes the decision.", 6500)
    pg.click('[data-ex="typical_defer"]'); expect("REVIEW REQUIRED"); p3 = pv(); assert "Borderline" in text(), "caption claims a borderline flag that is not on screen"
    cap(f"Weak evidence: P = {p3:.3f} is below the 0.90 threshold (and flagged as borderline). RakshaMarg does not guess: the trip is held for a supervisor.", 6500)
    pg.click("#d-log"); pg.click('nav.tabs button[data-tab="log"]'); pg.wait_for_timeout(300)
    tid = pg.get_attribute("[data-ap]", "data-ap"); pg.fill(f'[data-sv="{tid}"]', "Duty supervisor"); pg.fill(f'[data-sn="{tid}"]', "Accept extra time, fog advisory")
    pg.click(f'[data-ap="{tid}"][data-ch="recommended"]'); pg.wait_for_timeout(300); assert "Reviewed by Duty supervisor" in pg.inner_text("#tab-log")
    cap("The supervisor chooses the route; name, time and note are recorded in the trip's audit trail.", 6000)
    pg.click('nav.tabs button[data-tab="dispatch"]'); pg.click('[data-ex="no_legal_route"]'); expect("BLOCKED BY RESTRICTIONS")
    cap("In a configured truck no-entry window every route crosses a closed street, so it reports BLOCKED BY RESTRICTIONS rather than routing through them.", 6000)
    SNAP = ROOT / "docs/data/nh19_osm_snapshot.json"
    if SNAP.exists():                                             # real-roads scene only when a verified real snapshot is installed
        rep = json.load(open(ROOT / "outputs/test_results/real_snapshot_report.json")); LF = ROOT / "tests/vendor/leaflet"
        pg.route("**/leaflet.min.js", lambda q: q.fulfill(path=str(LF / "leaflet.js"), content_type="application/javascript"))
        pg.route("**/leaflet.min.css", lambda q: q.fulfill(path=str(LF / "leaflet.css"), content_type="text/css"))
        pg.route("**/tile.openstreetmap.org/**", lambda q: q.abort()); pg.route("**/api.open-meteo.com/**", lambda q: q.abort()); pg.route("**/api/interpreter", lambda q: q.abort())
        pg.click("#mode-real"); pg.wait_for_timeout(500); pg.select_option("#r-wx", "clear"); pg.click("#r-load"); pg.wait_for_selector("#decision .badge", timeout=60000); pg.wait_for_timeout(800)
        chk = pg.inner_text("details"); assert "west→east ✓" in chk and "saved OpenStreetMap snapshot" in pg.inner_text("#r-status"), chk
        b1 = badge(); km1 = re.search(r"min · ([0-9.]+) km", text()).group(1)
        cap(f"Experimental real-roads mode: {rep['stats']['edges']:,} OpenStreetMap road segments around Prayagraj (data as of {rep['osm_base'][:10]}). NH-19 west→east preset: {b1}. Scores are relative and uncalibrated; weather set manually in this recording.", 8000)
        pg.check('[data-z="1"]'); pg.wait_for_timeout(800); b2 = badge(); m2 = re.search(r"min · ([0-9.]+) km", text())
        effect = "blocks every route" if b2 == "BLOCKED BY RESTRICTIONS" else (f"reroutes the trip ({km1} km → {m2.group(1)} km)" if m2 and m2.group(1) != km1 else "leaves this route unaffected")
        cap(f"Turning on the Sangam / Mela-area no-vehicle zone (an illustrative advisory zone) {effect}.", 6000)
        pg.click("#mode-sim"); pg.wait_for_timeout(300)
    pg.click('[data-ex="typical_switch"]'); pg.click("#d-log"); pg.click('nav.tabs button[data-tab="log"]'); pg.wait_for_timeout(300)
    oc = pg.get_attribute("[data-ok]", "data-ok"); pg.fill(f'[data-oc="{oc}"]', "1"); pg.fill(f'[data-on="{oc}"]', "3"); pg.click(f'[data-ok="{oc}"]'); pg.wait_for_timeout(300)
    flag = "excess severe events flagged" if "excess severe events flagged" in pg.inner_text("#tab-log") else "no excess-event flag"
    cap(f"After the trip, observed crashes and near-misses are compared with the prediction ({flag}). It is a monitoring signal, not proof of model accuracy.", 6500)
    pg.click('nav.tabs button[data-tab="evidence"]'); pg.wait_for_timeout(300)
    cap(f"Simulated holdout: at +2% driving time the deployed blend cuts true risk {hf['mb2_blend']['mean']:.1f}% vs {hf['mb2_road']['mean']:.1f}% for road features alone (+{hf['blend_minus_road']['mean']:.1f} points, lost in {hf['blend_minus_road']['losses']} of 5 worlds). Browser = archived Python on {PAR['decisions_agree']}/{PAR['trips']} cases.", 8000)
    card("Score the route. Brief the driver. Bring everyone home.", "All fleet effects shown are simulated. The demo link also has an experimental real-roads mode (live OpenStreetMap + Open-Meteo, NH-19 Prayagraj). Next step: a shadow pilot on partner event and exposure data.", 5500)
    vid = pg.video.path(); ctx.close(); br.close()
mp4 = ROOT / "outputs/RakshaMarg_demo.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", vid, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24", "-movflags", "+faststart", str(mp4)], check=True)
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True).stdout)
json.dump(scenes, open(ROOT / "outputs/test_results/video_captions.json", "w"), indent=1)
print(f"video {dur:.0f} s, {mp4.stat().st_size/1e6:.1f} MB, {len(scenes)} asserted scenes"); [print(" -", s[:150]) for s in scenes]
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "30", "-i", str(mp4), "-frames:v", "1", "/tmp/v30.png"])
