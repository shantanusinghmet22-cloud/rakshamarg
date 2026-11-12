# Development / robustness suite

Source version d26a6e6bfe91 for every run. Dispatch scorer: RakshaMarg + braking blend (geometric: model rate x sqrt(braking rate / model mean rate)).
development and robustness suite: these seeds (7, 11, 23, 42, 101) informed development across v0.1-v0.3.
Segments per world: 523-534. Integrity: 0 inconsistent of 12000 decisions. Deferrals: 68 of 2398 dispatch trips.

## Surrogate fidelity: faithful (5 worlds)

| Method | Segment ranking | Sparse segments | Segment x context | Top-10% lift |
|---|---|---|---|---|
| Harsh brakes per road-km (naive) | 0.077 ± 0.063 | -0.041 | 0.081 | 2.57 |
| Crash history (smoothed rate) | 0.389 ± 0.039 | 0.206 | 0.338 | 3.53 |
| Harsh brakes per veh-km (smoothed) | 0.636 ± 0.015 | 0.443 | 0.544 | 3.76 |
| Road features only | 0.760 ± 0.018 | 0.718 | 0.849 | 3.93 |
| Road features + EB | 0.761 ± 0.017 | 0.718 | 0.850 | 3.92 |
| Road + telematics, no EB | 0.803 ± 0.007 | 0.754 | 0.861 | 3.93 |
| RakshaMarg, crash-only target | 0.714 ± 0.029 | 0.672 | 0.760 | 3.99 |
| RakshaMarg, trees only (no GLM base) | 0.784 ± 0.013 | 0.730 | 0.851 | 3.89 |
| RakshaMarg (full) | 0.799 ± 0.012 | 0.752 | 0.860 | 3.88 |
| RakshaMarg + braking blend | 0.749 ± 0.018 | 0.714 | 0.828 | 3.73 |
| Oracle (true risk) | 1.000 ± 0.000 | 1.000 | 1.000 | 3.81 |

True risk reduction at matched fleet-wide extra travel time (mean ± sd, %):

| Method | +1% time | +2% time | +4% time |
|---|---|---|---|
| Crash history | 4.7 ± 2.0 | 7.2 ± 2.9 | 9.9 ± 4.8 |
| Harsh brakes per veh-km | 5.9 ± 1.8 | 9.2 ± 2.3 | 13.2 ± 3.9 |
| RakshaMarg | 7.0 ± 0.8 | 10.5 ± 1.1 | 14.9 ± 1.6 |
| RakshaMarg + braking blend | 7.5 ± 1.3 | 11.5 ± 1.8 | 17.6 ± 2.5 |
| RakshaMarg + braking blend, point estimate | 7.6 ± 1.3 | 11.5 ± 1.7 | 17.5 ± 2.5 |
| Road features only | 6.4 ± 1.0 | 10.0 ± 1.6 | 15.3 ± 2.0 |

90% band coverage (dispatch scorer): 95.0% (min 91.8%); by context: day/clear 95.9% (min 91.9%), evening/rain 96.2% (min 94.1%), night/clear 90.6% (min 82.1%), night/fog 97.1% (min 92.7%)

## Surrogate fidelity: noisy (5 worlds)

| Method | Segment ranking | Sparse segments | Segment x context | Top-10% lift |
|---|---|---|---|---|
| Harsh brakes per road-km (naive) | 0.022 ± 0.060 | -0.062 | 0.033 | 2.45 |
| Crash history (smoothed rate) | 0.391 ± 0.035 | 0.227 | 0.338 | 3.49 |
| Harsh brakes per veh-km (smoothed) | 0.545 ± 0.020 | 0.397 | 0.467 | 3.56 |
| Road features only | 0.703 ± 0.014 | 0.676 | 0.804 | 3.37 |
| Road features + EB | 0.718 ± 0.017 | 0.680 | 0.812 | 3.82 |
| Road + telematics, no EB | 0.736 ± 0.018 | 0.721 | 0.805 | 3.28 |
| RakshaMarg, crash-only target | 0.663 ± 0.070 | 0.623 | 0.710 | 3.83 |
| RakshaMarg, trees only (no GLM base) | 0.741 ± 0.024 | 0.714 | 0.811 | 3.84 |
| RakshaMarg (full) | 0.747 ± 0.023 | 0.722 | 0.816 | 3.86 |
| RakshaMarg + braking blend | 0.721 ± 0.021 | 0.698 | 0.802 | 3.76 |
| Oracle (true risk) | 1.000 ± 0.000 | 1.000 | 1.000 | 3.81 |

True risk reduction at matched fleet-wide extra travel time (mean ± sd, %):

| Method | +1% time | +2% time | +4% time |
|---|---|---|---|
| Crash history | 4.0 ± 2.4 | 5.9 ± 3.1 | 10.1 ± 3.4 |
| Harsh brakes per veh-km | 4.8 ± 2.1 | 8.0 ± 2.5 | 11.8 ± 4.1 |
| RakshaMarg | 6.7 ± 1.0 | 10.2 ± 1.7 | 14.6 ± 1.8 |
| RakshaMarg + braking blend | 7.4 ± 1.2 | 11.3 ± 1.7 | 16.7 ± 2.2 |
| RakshaMarg + braking blend, point estimate | 7.3 ± 1.1 | 11.3 ± 1.6 | 16.8 ± 2.2 |
| Road features only | 5.7 ± 1.1 | 8.5 ± 1.6 | 11.9 ± 1.9 |

90% band coverage (dispatch scorer): 96.2% (min 93.0%); by context: day/clear 96.1% (min 86.8%), evening/rain 96.7% (min 94.2%), night/clear 94.1% (min 90.1%), night/fog 97.7% (min 95.2%)
