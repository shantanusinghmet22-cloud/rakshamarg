# RakshaMarg: pre-dispatch route risk decisions for fleet dispatchers (prototype v1.2)

**Team PLACER:** Shantanu Singh, IIT (BHU) Varanasi (shantanu.singh.met22@itbhu.ac.in). Netradyne Campus Innovation
Challenge 2026, theme *Fleet Route Risk Intelligence*.

RakshaMarg compares a dispatcher's candidate routes on estimated risk and extra driving time before a trip is
assigned. It returns one of four outcomes:
- **switch** to a lower-risk route;
- **keep** the fastest;
- **review required**: the trip is held for a supervisor when the evidence is weak;
- **blocked / no route**, with the cause stated.

**Read first:**
- All fleet effects are measured on a **simulated** fleet region with known ground truth.
- The real-roads mode is an **experimental** public-data adapter. Its risk scores are relative and uncalibrated.

## Quick start
1. **Console (no install):** open `docs/index.html` in Chrome, Edge or Firefox. It is hosted with GitHub Pages
   (Settings → Pages → `main` / `/docs`).
   - Start with *Fleet demo region* → *Typical switch*.
   - *Real roads* needs internet (OpenStreetMap Overpass + Open-Meteo).
2. **API:**
   ```bash
   pip install -r requirements.txt
   uvicorn api:app --port 8000          # http://localhost:8000/docs
   ```
   It serves from the versioned model export `model/rakshamarg_model_v1.json` and does not retrain.
3. **Tests:**
   ```bash
   python tests/test_pipeline.py && python tests/test_api.py
   node tests/test_engine.cjs && node tests/test_adapters.cjs
   pip install -r requirements-dev.txt && playwright install chromium
   python tests/e2e_console.py && python tests/e2e_real_mode.py
   ```

## What is built, experimental, and not yet modelled
| Area | Status |
|---|---|
| Decision engine (browser + API) from one model export; 300/300 archived Python cases matched on decision and fastest/considered/chosen routes | Built |
| Console: examples, map/typed origin-destination, policy sliders, decision card, verified explanations, bilingual brief template | Built |
| Supervisor review queue with audit record (name, time, note); idempotent logging; 30-column CSV export | Built |
| REST API: score → assign → review → outcome; SQLite store (survives restarts) | Built (local) |
| Simulated fleet pipeline: cleaning, segment snapping, hotspots, severe-event GLM × boosting + Empirical Bayes, paired uncertainty | Built (simulated data) |
| Real roads around Prayagraj (NH-19): live OSM + Open-Meteo. Directed graph with one-way / reverse one-way / roundabout semantics, `hgv` / `goods` / `motor_vehicle` / `access` exclusions, endpoints snapped to the strongly connected core, cause-specific no-route states, unknown-weather pause | **Experimental** |
| Restriction zones (segment–circle geometry, windows checked along estimated arrival times) | Built; presets illustrative, not official notifications |
| Turn restrictions, conditional access, weight/height limits (flagged, not enforced), live traffic speeds, per-segment weather, HMM matching of GPS traces | Not modelled |
| Real fleet calibration, Driveri integration | Next (pilot) |

## Evidence (simulated; 5 network realisations × 2 braking-proxy settings; holdout first run after the model was frozen)

**Default policy:**
- **Faithful proxy:** 12.9% lower expected crash risk for +1.81% fleet driving time.
- **Noisy proxy:** 13.0% lower risk for +1.65% time.
- **Switches with lower true risk:** 98%.

**At a matched +2% driving-time budget** (interpolated from per-trip budget sweeps), true risk reduction was:

| Method | Faithful | Noisy |
|---|---|---|
| Deployed blend | 11.4% | 11.2% |
| Model alone | 11.0% | 9.1% |
| Road features only (strongest simple baseline) | 9.9% | 9.5% |
| Braking per veh-km | 7.3% | 6.2% |
| Crash history | 3.8% | 4.7% |

**Gain over road features:**
- Faithful: per world [0.7, 2.6, -0.3, 1.4, 2.9] points; mean +1.5.
- Noisy: [1.3, 1.6, 1.8, 1.9, 2.0].

**Evaluated policy vs product behaviour:**
- The simulation scores review cases as if they kept the fastest route (fallback), with no supervisor waiting time.
- In the product those trips wait for a supervisor's choice.
- Review applied to 4.6% of holdout trips (1.3–11.3% by world).
- With a 46-minute average trip, **each 10 minutes of supervisor wait adds about 1.0 percentage points of fleet driving time**, on top of the routing cost.
- Supervisor choices could move the risk figures either way; this is not yet evaluated. Review speed is therefore a pilot gate.

**Supplementary analyses** (`analysis/`, outputs in `outputs/supplementary/`; the released model is not changed):
- **Challenger baseline:** smoothed severe events (near-misses + crashes) per veh-km.
  - Segment-risk ranking: 0.64 / 0.56 vs the model's 0.79 / 0.75.
  - Across segment × context, with context multipliers: 0.72 / 0.68 vs 0.87 / 0.82.
- **Pipeline sensitivity:** refitting on counts derived from the cleaned, map-matched event records (instead of the
  simulator's per-edge aggregates) gives ranking 0.794 / 0.738 (vs 0.794 / 0.749).
- **Scaling (synthetic grid benchmark, not a production load test):**
  - Decision latency p50 is 4.4 ms at 264 segments, 20.8 ms at 1,104, 171.9 ms at 4,512 and 1.7 s at 18,240. That is Yen k-shortest routing; state-scale networks need precomputed alternatives.
  - Ingestion runs at about 671k events/s up to 1.6 M events.

**Honest limits:**
- Interval coverage (97%) is high partly because the bands are wide.
- The comparison probability is model-based and uncalibrated.
- Review is conservative: 92% of the alternatives held for review were in fact lower-risk.
- 0 decision-object inconsistencies in 24,000 simulated method–trip evaluations. This is a consistency check, not a safety or legality guarantee.

Detailed v0.3 evaluation notes: `EVALUATION.md`, `outputs/HOLDOUT.md`, `outputs/MULTISEED.md`.

## Real-roads snapshot and final links
- **Saving a snapshot.** In the console, choose *Real roads* → *Load roads* (live), then *Download dated snapshot*.
- **Installing it.** Run `python scripts/finalize.py --snapshot nh19_osm_snapshot.json --links links.json`. This:
  - verifies both presets on the snapshot (`tests/verify_snapshot.cjs`, report in `outputs/test_results/`);
  - installs it as `docs/data/nh19_osm_snapshot.json` with ODbL attribution;
  - adds the public demo / repository / video links to the console.
- **Afterwards:** run `python tests/e2e_snapshot.py` and `python tests/record_demo.py`. The video adds asserted real-road scenes.
- **Hosting.** The hosted console (GitHub Pages, https) loads the saved snapshot first; *Reload roads* fetches live.
  A `file://` copy cannot read the snapshot (browser security), so it fetches live OpenStreetMap instead.

## Reproducibility and model versioning
- **Serving vs training.** The console and API serve the versioned export `model/rakshamarg_model_v1.json` (see
  `model/MODEL_CARD.md`), so decisions are identical across machines.
- **Retraining is approximate.** Retraining (`python run_demo.py && python export_web_data.py`) under the pinned
  `requirements.txt` reproduces the release exactly in our environment. On other platforms, cases within Monte-Carlo
  precision of a threshold can move.
- **Model-version policy.** A retrained model is a new model version and must be re-tested before serving.
- **Integrity checks.** `python verify_release.py` checks result fingerprints, and `sha256sum -c MANIFEST.sha256`
  checks every file. Test artefacts are written to `outputs/test_results/` and excluded from the manifest.

## Data and licences
- **Code:** MIT.
- **Map data:** © OpenStreetMap contributors, ODbL. Saved snapshots must keep this attribution.
- **Weather:** Open-Meteo, CC BY 4.0.
- **Leaflet:** BSD-2-Clause, vendored in `tests/vendor` for offline tests.
- **Background statistics:** MoRTH, *Road Accidents in India 2023*.

## Changelog
**v1.2 (follow-up review):**
- Repeat journeys are logged as new trips; deduplication is per scored decision.
- The driver brief is issued when a supervisor approves a review (console and API).
- The evaluated fallback policy and the supervisor-wait cost are stated.
- The scaling chart is labelled as a synthetic benchmark.
- "Load roads" prefers the saved snapshot.
- Snapshot verifier, finalize pipeline and asserted real-road video scenes (run once a real snapshot is supplied).

**v1.1 (independent judge review):**
- Video narration asserted against every on-screen decision.
- Real-road graph semantics: one-way, reverse, roundabout and access tags; connected-core snapping;
  segment–circle zones; en-route windows; parallel-road routes.
- Cause-specific no-route states.
- Unknown-weather pause with timeout and expiry.
- Experimental relative-risk display with input provenance.
- Supervisor review workflow.
- API served from the model export, with SQLite, separate score / assign / review / outcome steps.
- Verified explanations.
- Exact parity gate.
- Challenger baselines, pipeline sensitivity and scaling analyses.
- README / test hygiene; CI workflow.

**v1.0:** dispatcher console and real-roads adapter.

**v0.3.x:** model, evaluation and API.
