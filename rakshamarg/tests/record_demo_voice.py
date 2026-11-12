"""Narrated walkthrough (simulated fleet region): large captions + neural voice (Piper TTS; en-US 'lessac' voice trained on the Lessac Blizzard 2013 dataset, used under that dataset's licence, see https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html).
Pass A reads every value from the screen and writes the narration; the voice is synthesised; pass B records the video,
holding each scene for its narration and re-asserting every on-screen decision. Outputs:
  outputs/RakshaMarg_demo_voice.mp4, outputs/RakshaMarg_demo_captions.mp4 (silent), outputs/RakshaMarg_demo.srt"""
import json, os, pathlib, re, shutil, subprocess, sys, time, wave
from playwright.sync_api import sync_playwright
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "tests")); from _serve import serve
URL, _SRV = serve(ROOT / "docs"); TMP = ROOT / "outputs/video_tmp"; shutil.rmtree(TMP, ignore_errors=True); TMP.mkdir(parents=True)
VOICE = os.environ.get("RM_VOICE", "/home/claude/tts/en-us-lessac-medium.onnx")
EV = json.load(open(ROOT / "outputs/test_results/evidence_bundle.json")); PAR = json.load(open(ROOT / "outputs/test_results/parity_result.json")); hf = EV["holdout"]["faithful"]
CAP = """t=>{let c=document.getElementById('cap');if(!c){c=document.createElement('div');c.id='cap';c.style.cssText='position:sticky;top:0;z-index:99999;background:#0F161F;color:#fff;font:700 30px Calibri,Carlito,sans-serif;line-height:1.3;padding:16px 30px;min-height:104px;display:flex;align-items:center';document.body.prepend(c)};c.textContent=t}"""
CARD = """([a,b])=>{let c=document.getElementById('card');if(!c){c=document.createElement('div');c.id='card';c.style.cssText='position:fixed;inset:0;background:#1B2430;color:#fff;z-index:100000;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:Calibri,Carlito,sans-serif;text-align:center;padding:50px';document.body.appendChild(c)};c.style.display=a?'flex':'none';c.innerHTML='<div style=\"font-size:76px;font-weight:700\">Raksha<span style=\"color:#3CC283\">Marg</span></div><div style=\"font-size:38px;color:#F2B53A;margin-top:18px\">'+a+'</div><div style=\"font-size:26px;color:#C9D1DB;margin-top:26px;max-width:1200px;line-height:1.35\">'+b+'</div>'}"""
g = lambda x: f"{float(x):g}"


def walkthrough(pg, say, card):
    badge = lambda: pg.inner_text("#decision .badge"); text = lambda: pg.inner_text("#decision")
    def expect(label): got = badge(); assert got == label, f"screen shows {got}, narration expects {label}"
    pv = lambda: float(re.search(r"P\(lower expected risk\) = ([0-9.]+)", text()).group(1))
    trade = lambda: re.search(r"Trade-off: [−+](\d+)% expected crashes \(model\) for \+([0-9.]+) min", text()).groups()
    tab = lambda t: (pg.click(f'nav.tabs button[data-tab="{t}"]'), pg.wait_for_timeout(250))
    card("Pre-dispatch route risk decisions", "Prototype · Netradyne Campus Innovation Challenge 2026 · Team PLACER, IIT (BHU) Varanasi",
         "RakshaMarg: pre-dispatch route risk decisions for fleet dispatchers. A prototype by Team PLACER, from I.I.T. B.H.U. Varanasi.")
    pg.click('[data-ex="typical_switch"]'); pg.wait_for_timeout(250); expect("SWITCH"); cut, mins = trade(); p = pv()
    say(f"A typical trip (simulated region): the alternative has {cut}% lower expected crashes for {g(mins)} extra min. Evidence P = {p:.3f}, above 0.90 → SWITCH.",
        f"Here is a typical trip in the simulated fleet region. The alternative route has {cut} percent lower expected crashes, for {g(mins)} extra minutes. The evidence is above the threshold, so RakshaMarg recommends a switch.")
    pg.evaluate("()=>{const s=document.querySelector('#p-mc');s.value=50;s.dispatchEvent(new Event('input'))}"); pg.wait_for_timeout(250); expect("KEEP FASTEST")
    say("The fleet sets the policy: if it demands a 50% risk reduction, the same trip no longer qualifies → KEEP FASTEST.",
        "The fleet sets the policy. If it demands a fifty percent risk reduction, the same trip no longer qualifies, so the fastest route is kept.")
    pg.click('[data-ex="selected_switch"]'); pg.wait_for_timeout(250); expect("SWITCH"); cut2, mins2 = trade()
    say(f"Selected illustration, night and dense fog: the fastest route uses an unlit NH stretch with median cuts. The alternative: {cut2}% lower expected crashes for {g(mins2)} extra min.",
        f"A selected illustration: night, in dense fog. The fastest route uses an unlit highway stretch with median cuts. The alternative has {cut2} percent lower expected crashes, for {g(mins2)} extra minutes.")
    pg.select_option("#s-tb", "day"); pg.select_option("#s-w", "clear"); pg.wait_for_timeout(300); b2 = badge()
    if b2 == "SWITCH":
        cut3, mins3 = trade()
        say(f"Same trip by day in clear weather: still a switch, but the gain shrinks to {cut3}% for {g(mins3)} extra min. Context changes the decision.",
            f"The same trip by day, in clear weather, is still a switch, but the gain shrinks to {cut3} percent. Time and weather change the decision.")
    else:
        say(f"Same trip by day in clear weather: the decision becomes {b2}. Context changes the decision.", f"The same trip by day, in clear weather, becomes {b2.lower()}. Time and weather change the decision.")
    pg.click('[data-ex="typical_defer"]'); pg.wait_for_timeout(250); expect("REVIEW REQUIRED"); p3 = pv(); assert "Borderline" in text()
    say(f"Weak evidence: P = {p3:.3f} is below 0.90 and flagged borderline. RakshaMarg does not guess; it holds the trip for a supervisor.",
        "Here the evidence is weak, just below the threshold. RakshaMarg does not guess. It holds the trip for a supervisor.")
    pg.click("#d-log"); tab("log"); tid = pg.get_attribute("[data-ap]", "data-ap")
    pg.fill(f'[data-sv="{tid}"]', "Duty supervisor"); pg.fill(f'[data-sn="{tid}"]', "Accept extra time, fog advisory"); pg.click(f'[data-ap="{tid}"][data-ch="recommended"]'); pg.wait_for_timeout(250)
    lg = pg.inner_text("#tab-log"); assert "Reviewed by Duty supervisor" in lg and "Driver brief issued" in lg
    say("The supervisor chooses the route. Name, time and note are recorded, and the driver brief is issued.",
        "The supervisor chooses the route. Their name, the time and a note are recorded, and the driver brief is issued.")
    tab("dispatch"); pg.click('[data-ex="no_legal_route"]'); pg.wait_for_timeout(250); expect("BLOCKED BY RESTRICTIONS")
    say("During a truck no-entry window every route crosses a closed street, so it reports BLOCKED BY RESTRICTIONS instead of routing through.",
        "During a truck no-entry window, every route crosses a closed street. So RakshaMarg reports that the trip is blocked, instead of routing through it.")
    pg.click('[data-ex="typical_switch"]'); pg.wait_for_timeout(250); pg.click("#d-log"); tab("log")
    oc = pg.get_attribute("[data-ok]", "data-ok"); pg.fill(f'[data-oc="{oc}"]', "1"); pg.fill(f'[data-on="{oc}"]', "3"); pg.click(f'[data-ok="{oc}"]'); pg.wait_for_timeout(250)
    flagged = "excess severe events flagged" in pg.inner_text("#tab-log")
    say(f"After the trip, observed crashes and near-misses are checked against the prediction ({'excess events flagged' if flagged else 'no flag'}). A monitoring signal, not proof of accuracy.",
        "After the trip, observed crashes and near misses are checked against the prediction. This is a monitoring signal, not proof that the model is right.")
    tab("evidence")
    say(f"Simulated holdout: at 2% extra driving time the deployed model cuts true risk {hf['mb2_blend']['mean']:.1f}% vs {hf['mb2_road']['mean']:.1f}% for road features alone. Browser = Python on {PAR['decisions_agree']}/{PAR['trips']} cases.",
        f"In simulated holdout worlds, at two percent extra driving time, the deployed model cuts true risk by {hf['mb2_blend']['mean']:.1f} percent, versus {hf['mb2_road']['mean']:.1f} percent for road features alone. The browser and the Python engine agree on all {PAR['trips']} reference cases.")
    card("Score the route. Brief the driver. Bring everyone home.", "All fleet effects shown are simulated. The demo link also has an experimental real-roads mode for NH-19 around Prayagraj. Next step: a shadow pilot on partner event and exposure data.",
         "Score the route. Brief the driver. Bring everyone home. All fleet effects shown are simulated. Our next step is a shadow pilot on partner event data.")


def run(record, durs=None):
    out = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        kw = dict(viewport={"width": 1440, "height": 960}); kw.update(record_video_dir=str(TMP), record_video_size={"width": 1440, "height": 960}) if record else None
        ctx = br.new_context(**kw); t0 = time.monotonic(); pg = ctx.new_page()
        pg.route("**/cdnjs.cloudflare.com/**", lambda r: r.abort()); pg.goto(URL); pg.wait_for_timeout(900 if record else 300)
        def hold(i): pg.wait_for_timeout(int(1000 * (durs[i] + 0.7))) if record else None
        def say(c, s):
            i = len(out); pg.evaluate(CAP, c); out.append(dict(caption=c, speech=s, t=time.monotonic() - t0)); hold(i)
        def card(a, b, s):
            i = len(out); pg.evaluate(CARD, [a, b]); out.append(dict(caption=a, speech=s, t=time.monotonic() - t0)); hold(i); pg.evaluate(CARD, ["", ""])
        walkthrough(pg, say, card)
        vid = pg.video.path() if record else None; ctx.close(); br.close()
    return out, vid


scenes, _ = run(False)                                                            # pass A: values from the screen
from piper import PiperVoice
voice = PiperVoice.load(VOICE); durs = []
for i, s in enumerate(scenes):
    with wave.open(str(TMP / f"n{i:02d}.wav"), "wb") as w: voice.synthesize_wav(s["speech"], w)
    with wave.open(str(TMP / f"n{i:02d}.wav")) as w: durs.append(w.getnframes() / w.getframerate())
rec, vid = run(True, durs)                                                        # pass B: record, holding each scene for its narration
assert [r["caption"] for r in rec] == [s["caption"] for s in scenes], "screen values changed between passes"
inputs, filt = ["-i", vid], []
for i, r in enumerate(rec):
    inputs += ["-i", str(TMP / f"n{i:02d}.wav")]; filt.append(f"[{i+1}:a]aresample=44100,adelay=delays={int(r['t']*1000)+250}:all=1[a{i}]")
filt.append("".join(f"[a{i}]" for i in range(len(rec))) + f"amix=inputs={len(rec)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
OUTV = ROOT / "outputs/RakshaMarg_demo_voice.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "0:v", "-map", "[aout]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(OUTV)], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(OUTV), "-an", "-c:v", "copy", "-movflags", "+faststart", str(ROOT / "outputs/RakshaMarg_demo_captions.mp4")], check=True)
ts = lambda x: f"{int(x//3600):02d}:{int(x%3600//60):02d}:{int(x%60):02d},{int(x%1*1000):03d}"
open(ROOT / "outputs/RakshaMarg_demo.srt", "w").write("\n".join(f"{i+1}\n{ts(r['t'])} --> {ts(r['t'] + durs[i] + 0.6)}\n{r['speech']}\n" for i, r in enumerate(rec)))
json.dump(rec, open(ROOT / "outputs/test_results/video_narration.json", "w"), indent=1)
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(OUTV)], capture_output=True, text=True).stdout)
print(f"voiced video {dur:.0f} s, {OUTV.stat().st_size/1e6:.1f} MB, {len(rec)} narrated + asserted scenes; narration {sum(durs):.0f} s")
for t in (12, 40): subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(OUTV), "-frames:v", "1", f"/tmp/vv{t}.png"])
