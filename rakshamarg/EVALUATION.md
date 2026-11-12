# RakshaMarg evaluation notes (model v0.3.2, unchanged in v1.1)

**Team PLACER:** Shantanu Singh, IIT (BHU) Varanasi (shantanu.singh.met22@itbhu.ac.in)

**Netradyne Campus Innovation Challenge 2026, theme: Fleet Route Risk Intelligence**

RakshaMarg compares a dispatcher's **truck-legal** candidate routes *before* a truck leaves, for that departure
time and weather. It returns **one explicit decision object** covering:
- the fastest route;
- the alternative it considered;
- the route it chose;
- the decision (`switch`, `keep`, `defer` or `no_legal_route`);
- the probability behind the decision.

> **Read first.** Every number here is measured on a **simulated** fleet region with known ground truth. Real
> fleet telematics with crash labels is not public in India. These results validate the *method*. They are not
> measured crash reductions on real roads.

**Frozen release:** source fingerprint `d26a6e6bfe91`, recorded in every `metrics.json`, the summary and
every API response. **Dispatch scorer everywhere** (evaluation, examples, demo, API default):
`RakshaMarg + braking blend (geometric: model rate x sqrt(braking rate / model mean rate))`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # exact versions used (Python 3.12.3)
python run_demo.py                       # ~60 s: primary world, figures, demo page, model artifacts
python tests/test_pipeline.py            # regression tests for every review finding
python tests/test_api.py                 # API: decisions shown = decisions made
uvicorn api:app --port 8000              # optional local server: http://localhost:8000/docs
# endpoints: POST /v1/route-risk | POST /v1/trips/{id}/outcome | GET /v1/hotspots | GET /v1/routes/high-risk | GET /health
# all 10 worlds (~10 min), then: python summarize_seeds.py  (fails if runs come from different source versions)
for fid in faithful noisy; do for s in 7 11 23 42 101; do
  python run_demo.py --seed $s --fidelity $fid --no-figures --out outputs/seeds/${fid}_seed$s; done; done
```
Open `outputs/dispatcher_demo.html` in a browser for the offline dispatcher demo.

## 1. Built vs. planned

| Component | Status |
|---|---|
| Synthetic Indian fleet region + telematics generator with ground truth (`world.py`) | Built |
| Cleaning, de-duplication, outlier removal | Built |
| Map-matching | Nearest-segment snapping built. **HMM trace matching: planned** |
| Hotspot engine (severity x recency, exposure-normalised, DBSCAN) | Built |
| Risk model: Poisson GLM x boosted residual on severe events, calibrated to crashes, Empirical Bayes | Built |
| Dispatch scorer: geometric blend of model and braking rate | Built |
| Uncertainty bands (validation-measured dispersion + bootstrap + scorer disagreement, paired draws) | Built, **experimental** |
| Truck no-entry windows, **with no silent fallback**: `no_legal_route` instead | Built (simulated rule set) |
| Policy, Pareto, evidence check over **all** qualifying alternatives, deferral | Built |
| Integrity rule: a switch never shows the fastest route; keep/defer always assign it | Built, enforced in every run and API call |
| REST API (FastAPI + uvicorn, local) with tests | Built |
| T6 trip log: every API decision logged with chosen route, risk index, expected crashes (`outputs/trip_log.jsonl`); evaluation log with route + risk (`dispatch_log.csv`) | Built |
| T6 post-trip comparison: `POST /v1/trips/{id}/outcome` tests observed severe events against the route's prediction (Poisson tail) | Built |
| T7 trends by month x road class and month x region; high-risk route records; search via `GET /v1/hotspots`, `GET /v1/routes/high-risk` | Built |
| T5 risk heat-map overlaid on route maps (figure and demo page, context-specific) | Built |
| Dispatcher console | Offline demo page built. **Web console: planned** |
| Driver brief EN/HI | **Templates** built. **WhatsApp/IVR and LLM wording: planned** |
| Public-data connectors (OSM, Open-Meteo, MoRTH, VIIRS, SRTM) | **Planned** |
| Real fleet events / crash labels | **Requires partner data** |

## 2. Results across 10 simulated worlds (523-534 segments each)

There are 5 random worlds for each of two assumptions about harsh braking as a crash proxy: **faithful**
(braking tracks risk closely) and **noisy** (an equal-coefficient mixture of risk-related and
congestion-related braking; the realised share is not exactly half).
This is the **development / robustness suite**: seeds 7, 11, 23, 42 and 101 informed development across v0.1-v0.3, so they are not untouched holdouts.

**Integrity checks:** 0 inconsistent decisions out of 12,000.

**Segment ranking** (rank correlation with true risk, held-out months, mean ± sd):

| Method | Faithful | Noisy | Faithful, seg x context | Noisy, seg x context |
|---|---|---|---|---|
| Crash history (smoothed rate) | 0.39 ± 0.04 | 0.39 ± 0.04 | 0.34 | 0.34 |
| Harsh brakes per veh-km (smoothed) | 0.64 ± 0.01 | 0.55 ± 0.02 | 0.54 | 0.47 |
| Road features only | 0.76 ± 0.02 | 0.70 ± 0.01 | 0.85 | 0.80 |
| Road + telematics, no EB | 0.80 ± 0.01 | 0.74 ± 0.02 | 0.86 | 0.81 |
| RakshaMarg, crash-only target | 0.71 ± 0.03 | 0.66 ± 0.07 | 0.76 | 0.71 |
| RakshaMarg, trees only (no GLM base) | 0.78 ± 0.01 | 0.74 ± 0.02 | 0.85 | 0.81 |
| RakshaMarg (full) | 0.80 ± 0.01 | 0.75 ± 0.02 | 0.86 | 0.82 |
| RakshaMarg + braking blend | 0.75 ± 0.02 | 0.72 ± 0.02 | 0.83 | 0.80 |

**True fleet risk reduction at a matched travel-time budget (%):**

| Method | Faithful, +2% | Noisy, +2% | Faithful, +4% | Noisy, +4% |
|---|---|---|---|---|
| Crash history | 7.2 ± 2.9 | 5.9 ± 3.1 | 9.9 | 10.1 |
| Harsh brakes per veh-km | 9.2 ± 2.3 | 8.0 ± 2.5 | 13.2 | 11.8 |
| Road features only | 10.0 ± 1.6 | 8.5 ± 1.6 | 15.3 | 11.9 |
| RakshaMarg | 10.5 ± 1.1 | 10.2 ± 1.7 | 14.9 | 14.6 |
| RakshaMarg + braking blend | 11.5 ± 1.8 | 11.3 ± 1.7 | 17.6 | 16.7 |

**Default policy.** The ≥15% risk cut is measured on the 80th-percentile risk, at ≤12% extra time, and the
switch also requires P(truly safer) ≥ 0.90.

| Risk source | Faithful: true cut | time | switches truly safer | Noisy: true cut | time | switches truly safer |
|---|---|---|---|---|---|---|
| Crash history | 7.5% | +2.5% | 77% | 8.6% | +2.4% | 79% |
| Harsh brakes per veh-km | 9.3% | +1.6% | 91% | 8.0% | +1.5% | 89% |
| Road features only | 13.1% | +2.2% | 95% | 10.4% | +2.3% | 90% |
| RakshaMarg | 12.4% | +1.9% | 95% | 12.1% | +2.2% | 94% |
| RakshaMarg + braking blend | 12.1% | +1.7% | 97% | 11.0% | +1.4% | 97% |

**Deferrals (dispatch scorer):** 68 of 2,398 trips. In 87% of
them the considered alternative was actually safer. That is the cost of caution, and the threshold is a fleet
setting.

**No-legal-route trips** (correctly refused, previously silently illegal): 2.

**90% bands for the dispatch scorer:**
- Coverage: 95% faithful (model-only scorer 93%), 96% noisy.
- By context, faithful: day/clear 96% (worst 92%), evening/rain 96% (worst 94%), night/clear 91% (worst 82%), night/fog 97% (worst 93%).
- By context, noisy: day/clear 96% (worst 87%), evening/rain 97% (worst 94%), night/clear 94% (worst 90%), night/fog 98% (worst 95%).
- **Still experimental:** night/clear remains the weakest context.

### Honest findings
- **Exposure normalisation is the biggest single win.** Braking per road-km ranks at about 0.05; per veh-km at
  about 0.6.
- **A simple exposure-normalised braking rate is a strong baseline.** On the development world it nearly matched
  us. Only 10 worlds showed the advantage clearly.
- **Training on severe events** (near-misses + crashes) instead of crashes alone is the most valuable modelling
  choice.
- **The blend ranks segments slightly worse than the model alone**, but makes better route decisions. We use the
  model for hotspots and ranking, and the blend for dispatch.
- **v0.2's bands under-covered the blend** (about 69% at day/clear). Adding the two scorers' disagreement as
  uncertainty fixed most of it.
- **Empirical Bayes is modest.** It mainly helps extreme segments when the proxy is noisy.


## 2b. Holdout: 10 worlds first run after the method was frozen

Seeds 202, 303, 404, 505 and 606 were run under both proxy settings with the unchanged v0.3 code (same
fingerprint). They have 527-540 segments each. Across all 20 worlds,
event counts are about 3.8-5.0 lakh (faithful) and 3.1-3.8 lakh (noisy). Full tables are in
`outputs/HOLDOUT.md`.

| Measure (holdout mean) | Faithful | Noisy |
|---|---|---|
| Segment ranking: RakshaMarg model | 0.794 | 0.749 |
| Segment ranking: braking per veh-km | 0.652 | 0.573 |
| True risk cut at +2% time: blend | 11.4% ± 2.3 | 11.2% ± 1.8 |
| True risk cut at +2% time: braking per veh-km | 7.3% ± 5.9 | 6.2% ± 5.6 |
| Default policy: true risk cut / extra time | 12.9% / +1.81% | 13.0% / +1.65% |
| Switches truly safer | 97.7% | 97.2% |
| 90% band coverage (worst night/clear world) | 97.4% (96%) | 96.4% (93%) |

**Other holdout counts:**
- Deferrals: 110 of 2,394 trips. In
  92% of them the considered option was in
  fact safer, so deferral is confirmed as conservative.
- No-legal-route trips: 6.
- Route-assignment rule violations: 0 of 12,000
  evaluated decisions.

**Scope of these claims:**
- The 0-violation count refers to the internal invariant: a switch shows a route different from the fastest;
  keep/defer assign the fastest; no-legal-route assigns nothing. It does not mean zero possible defects.
- Uncertainty probabilities are model-based. High synthetic coverage can partly reflect wider bands, so
  band-width reporting is planned alongside coverage.
- Per-trip decisions and selected examples can differ slightly on other platforms (an external audit on
  macOS/Python 3.12.14 saw 83/149/7 vs 85/148/6 switch/keep/defer). Aggregates agreed closely. The submitted
  release environment is the reference.

## 3. Method
1. **Severe-event model.** A Poisson GLM multiplied by a boosted residual, trained on (near-misses + crashes) per
   veh-km and calibrated to crash rate. It is then corrected per segment with Empirical Bayes (Gamma-Poisson,
   prior strength k tuned on validation months).
2. **Dispatch scorer.** `rate_blend = rate_model x sqrt(rate_braking / mean_rate_model)`. Context effects come
   from the model; the per-road level is a 50/50 geometric blend with the exposure-normalised braking rate.
3. **Uncertainty.** NB dispersion of the *deployed scorer* is measured on validation months, using models built
   only on earlier months. It is combined with bootstrap spread, scorer disagreement `|log w|` and context
   sparsity.
   - Draws are shared by road class and context.
   - The same draws are used for every route in a trip, so comparisons are **paired**.
4. **Decision.**
   - Build truck-legal candidates (none means `no_legal_route`) and take the Pareto frontier on the
     80th-percentile risk.
   - Alternatives qualify if they cut that risk by ≥15% for ≤12% extra time.
   - Check them in policy-value order: the first with P(safer) ≥ 0.9 is chosen. Otherwise defer, showing the
     best-evidenced alternative.

## 4. Simulation assumptions (all in `rakshamarg/world.py`)
- **Network:** NH corridor (median openings, mostly unlit), SH, urban core with no-entry market streets, ghat
  section, district roads.
- **Hidden risk:** unobserved heterogeneity (log-sd 0.5), plus hidden-hazard segments no map attribute reveals.
- **Public list:** an incomplete black-spot list.
- **Weather and time:** seasonal rain and fog, plus night/unlit multipliers.
- **Data quality:** 12 m GPS noise and 2% bad records.
- **Primary world:** 523 segments, 12.4 M veh-km and 689 crashes.
- **Limitations:** the generator and the model were written by the same team, so real fleet data is required
  for validation.

## 5. Reproducibility
- Exact versions are pinned in `requirements.txt`, including uvicorn. Seeded RNGs; no Python `hash()`.
- `summarize_seeds.py` refuses to summarise runs from different source versions.
- Primary-world checks: snapping accuracy 98.7% with 12 m GPS noise.
- **Microbenchmarks:** single CPU core, in-process, 523-segment synthetic graph; not a service load test. Full decision: 12.9 ms.

## 6. Changelog
**v0.3.2 (self-audit against the theme's task list):** heat-map overlay on route maps (T5); trip log with route and
risk score, plus an API post-trip comparison (T6); region and route trend reports, plus hotspot and high-risk route
search (T7); MoRTH primary source and straight-road statistic verified. All 21 runs were regenerated under fingerprint
`d26a6e6bfe91`; headline results are unchanged.

**v0.3.1 (third external review):** fresh 10-world holdout, corrected event-count and proxy wording, seed-suite
labelling, scoped integrity claim, full-release `MANIFEST.sha256`, and a sources list. No change to model code;
the fingerprint is unchanged.

**v0.3 (fixes from the second external review)**
1. **Truck rules can no longer be silently dropped.** When no legal route exists, the result is
   `no_legal_route` (review required). Covered by a regression test.
2. **The API and demo display the exact decision object.** There is no recomputation, and every run and request
   is checked (0 inconsistencies).
3. **The deployed blend has its own uncertainty and coverage evaluation.** This includes validation-measured
   dispersion and scorer disagreement.
4. **All outputs come from one frozen release.** That covers all 10 worlds, the summary, examples, demo, API
   artifacts and the deck. The source fingerprint and scorer are recorded throughout.
5. **Smaller fixes:**
   - every qualifying alternative is checked before deferring;
   - uvicorn added to requirements;
   - segment counts are reported as a range;
   - blend formula and threshold statistic documented.

**v0.2:** stronger baselines and ablations, 10 worlds, severe-event target, GLM base, paired uncertainty with
deferral, truck rules, REST API, offline demo, pinned environment.

## 7. Sources
- MoRTH, Road Accidents in India 2023 (official report): https://morth.nic.in/sites/default/files/Road-Accident-in-India-2023-Publications.pdf
- MoRTH 2023 totals and NH/SH shares of deaths (PTI): https://www.dtnext.in/news/national/172-lakh-people-died-in-480-lakh-road-accidents-in-2023-road-ministry-report-844831
- 67% of crashes on straight roads (MoRTH 2023, Vikaspedia): https://en.vikaspedia.in/viewcontent/news/road-accidents-in-india?lgn=en
- Summary of MoRTH 2023 (per-hour figures, National + State Highways share, straight roads): https://visionias.in/current-affairs/news-today/2025-08-29/society/road-accidents-in-india-2023-report-released-by-ministry-of-road-transport-and-highways
- Black-spot corridors (e-DAR, Rajya Sabha reply): https://www.outlookindia.com/national/accident-prone-highway-black-corridors-claims-37164-lives-in-three-years
- NCRB 2023 summary (time of day): https://visionias.in/current-affairs/upsc-daily-news-summary/article/2025-10-01/the-hindu/polity-and-governance/over-173-lakh-killed-in-road-accidents-in-2023-over-speeding-a-major-cause-ncrb
- Netradyne RiskMap (2018): https://www.netradyne.com/news/netradyne-introduces-new-riskmap-feature-to-identify-geographic-risk
- Licences: OSM https://www.openstreetmap.org/copyright, Open-Meteo https://open-meteo.com/en/licence, GODL-India https://data.gov.in/government-open-data-license-india

## 8. Release integrity
- `python verify_release.py`: every saved result (primary, development suite, holdout) carries the model and
  evaluation fingerprint of the shipped code.
- `sha256sum -c MANIFEST.sha256`: checksum of **every** file in the archive, including the API, tests and
  requirements.

## 9. Positioning
Netradyne's Driveri **RiskMap** (announced March 2018) clusters risky driving behaviour by location. RakshaMarg is
the decision layer on top: exposure-normalised, context-aware, truck-legal route choice within a time budget,
with an explicit "defer" or "no legal route" when it cannot recommend safely.

Licence: MIT.

---

## Prototype v1.0 (Prototype Phase): dispatcher console

**Live console:** `docs/index.html` is one self-contained file. Host it with GitHub Pages (Settings → Pages →
Deploy from branch → `main` / `/docs`), or just double-click it to run offline.

**What the console contains:**
- **Fleet demo region (simulated data).** The full trained engine, with identical decisions to the Python API. It
  covers examples, map clicks, time and weather, policy sliders, the decision card with reasons, a bilingual
  brief, the trip log with post-trip check, hotspot search, analytics and evidence.
- **Real roads: NH-19 around Prayagraj.** Live OpenStreetMap roads (Overpass API) and the live Open-Meteo
  forecast, fetched in your browser, plus time-windowed restriction zones.
  - This is a cold-start model: road features only, with no fleet history, so it often keeps or defers.
  - After a live load, "Download snapshot" saves `nh19_osm_snapshot.json`. Put it in `docs/data/` to make demos
    independent of the public OSM servers.

**Build and test**
```bash
python run_demo.py && python export_web_data.py   # trained engine -> web/data_sim.js (+ Python reference trips)
node tests/test_engine.cjs                        # browser engine vs Python API: identical decisions on reference trips
python build_web.py                               # -> docs/index.html
python tests/e2e_console.py                       # Playwright: every example, tab, log and post-trip check
python tests/e2e_real_mode.py                     # Playwright: real-roads mode with Overpass/Open-Meteo-format mocks
python tests/record_demo.py                       # captioned demo video (numbers read from the release files)
```

**Engine parity:** `web/parity_result.json` records candidate routes and decisions identical to the Python
reference on all reference trips. The browser receives the engine's exact uncertainty draws (int16 log-quantised),
so it does not re-sample.

**Reproducibility note:** at the start of this phase, a sandbox library upgrade (numpy 2.5, scikit-learn 1.9)
shifted results slightly. Re-installing `requirements.txt` restored an exact match with the released numbers, so
always use the pinned versions.
