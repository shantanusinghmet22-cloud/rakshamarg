# Holdout: worlds first run after the method was frozen

Source version d26a6e6bfe91 for every run. Dispatch scorer: RakshaMarg + braking blend (geometric: model rate x sqrt(braking rate / model mean rate)).
true holdout: seeds 202-606 were first run after the v0.3 method was frozen (fingerprint unchanged).
Segments per world: 527-540. Integrity: 0 inconsistent of 12000 decisions. Deferrals: 110 of 2394 dispatch trips.

## Surrogate fidelity: faithful (5 worlds)

| Method | Segment ranking | Sparse segments | Segment x context | Top-10% lift |
|---|---|---|---|---|
| Harsh brakes per road-km (naive) | 0.064 ± 0.076 | -0.040 | 0.059 | 1.83 |
| Crash history (smoothed rate) | 0.353 ± 0.029 | 0.218 | 0.310 | 2.84 |
| Harsh brakes per veh-km (smoothed) | 0.652 ± 0.027 | 0.457 | 0.549 | 2.95 |
| Road features only | 0.725 ± 0.025 | 0.671 | 0.837 | 3.15 |
| Road features + EB | 0.731 ± 0.025 | 0.672 | 0.839 | 3.31 |
| Road + telematics, no EB | 0.794 ± 0.019 | 0.711 | 0.866 | 3.11 |
| RakshaMarg, crash-only target | 0.694 ± 0.030 | 0.637 | 0.744 | 3.14 |
| RakshaMarg, trees only (no GLM base) | 0.783 ± 0.024 | 0.693 | 0.852 | 3.21 |
| RakshaMarg (full) | 0.794 ± 0.019 | 0.709 | 0.867 | 3.22 |
| RakshaMarg + braking blend | 0.763 ± 0.029 | 0.685 | 0.846 | 3.29 |
| Oracle (true risk) | 1.000 ± 0.000 | 1.000 | 1.000 | 3.42 |

True risk reduction at matched fleet-wide extra travel time (mean ± sd, %):

| Method | +1% time | +2% time | +4% time |
|---|---|---|---|
| Crash history | 2.0 ± 5.5 | 3.8 ± 6.8 | 6.2 ± 6.9 |
| Harsh brakes per veh-km | 4.6 ± 5.5 | 7.3 ± 5.9 | 10.9 ± 7.0 |
| RakshaMarg | 7.7 ± 1.5 | 11.0 ± 2.0 | 16.5 ± 3.0 |
| RakshaMarg + braking blend | 8.1 ± 1.8 | 11.4 ± 2.3 | 18.2 ± 3.3 |
| RakshaMarg + braking blend, point estimate | 8.1 ± 1.8 | 11.4 ± 2.4 | 18.1 ± 3.2 |
| Road features only | 7.1 ± 1.5 | 9.9 ± 1.6 | 16.2 ± 2.7 |

90% band coverage (dispatch scorer): 97.4% (min 96.7%); by context: day/clear 95.6% (min 89.8%), evening/rain 97.2% (min 94.7%), night/clear 97.4% (min 95.8%), night/fog 99.3% (min 98.3%)

## Surrogate fidelity: noisy (5 worlds)

| Method | Segment ranking | Sparse segments | Segment x context | Top-10% lift |
|---|---|---|---|---|
| Harsh brakes per road-km (naive) | 0.018 ± 0.071 | -0.046 | 0.018 | 1.71 |
| Crash history (smoothed rate) | 0.381 ± 0.030 | 0.172 | 0.327 | 2.71 |
| Harsh brakes per veh-km (smoothed) | 0.573 ± 0.025 | 0.375 | 0.473 | 2.79 |
| Road features only | 0.685 ± 0.019 | 0.656 | 0.800 | 2.86 |
| Road features + EB | 0.702 ± 0.012 | 0.657 | 0.808 | 2.99 |
| Road + telematics, no EB | 0.737 ± 0.029 | 0.700 | 0.813 | 2.90 |
| RakshaMarg, crash-only target | 0.681 ± 0.012 | 0.646 | 0.731 | 2.99 |
| RakshaMarg, trees only (no GLM base) | 0.745 ± 0.025 | 0.701 | 0.817 | 2.92 |
| RakshaMarg (full) | 0.749 ± 0.024 | 0.699 | 0.822 | 2.93 |
| RakshaMarg + braking blend | 0.733 ± 0.036 | 0.683 | 0.819 | 3.10 |
| Oracle (true risk) | 1.000 ± 0.000 | 1.000 | 1.000 | 3.41 |

True risk reduction at matched fleet-wide extra travel time (mean ± sd, %):

| Method | +1% time | +2% time | +4% time |
|---|---|---|---|
| Crash history | 3.3 ± 3.5 | 4.7 ± 3.7 | 8.9 ± 2.5 |
| Harsh brakes per veh-km | 4.3 ± 5.4 | 6.2 ± 5.6 | 9.8 ± 6.4 |
| RakshaMarg | 6.8 ± 1.6 | 9.1 ± 1.8 | 14.7 ± 3.3 |
| RakshaMarg + braking blend | 8.1 ± 1.5 | 11.2 ± 1.8 | 18.3 ± 2.6 |
| RakshaMarg + braking blend, point estimate | 8.3 ± 1.5 | 11.4 ± 1.8 | 18.3 ± 2.6 |
| Road features only | 7.0 ± 1.7 | 9.5 ± 1.6 | 14.7 ± 2.9 |

90% band coverage (dispatch scorer): 96.4% (min 95.0%); by context: day/clear 97.6% (min 94.3%), evening/rain 93.1% (min 89.5%), night/clear 96.4% (min 93.0%), night/fog 98.3% (min 96.0%)
