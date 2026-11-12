# RakshaMarg model export v1

- File: `rakshamarg_model_v1.json` (sha256 prefix `fd47a185cf0d`)
- Produced by `export_web_data.py` from the training run with source fingerprint `d26a6e6bfe91`
- Contents:
  - dispatch-scorer segment rates for 9 time-of-day × weather contexts;
  - the model's paired uncertainty draws (int16 log-quantised, step 1/4000);
  - risk-index references;
  - the hotspot registry;
  - a cold-start road-feature GLM for the experimental real-roads mode;
  - the network.
- Used by:
  - the browser console (`docs/index.html`);
  - the REST API (`api.py`).

  Neither retrains. Decisions are therefore identical across machines and match the archived Python reference on 300/300 trips.
- Retraining (`run_demo.py`) is a separate, approximate process. On a different platform it can move cases that lie
  within Monte-Carlo precision of a policy threshold. An external audit on macOS/Python 3.12.14 saw one saved case
  move from P=0.897 to P=0.900.
- **Policy:** a retrained model is a new model version. It must be re-exported, re-tested and re-labelled before
  serving.
- **Data:** fully simulated. It is not calibrated to real fleet crashes.
