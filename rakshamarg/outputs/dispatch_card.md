# Dispatch card (SIMULATED, selected example) - trip (1, 0) -> (21, 2)

Context: night departure, fog. Selected as the largest predicted improvement among west-east trips; see
`dispatch_cases.json` for typical switch / keep / defer cases.

| Option | Time | Distance | Risk index | Exp. crashes / 1,000 trips (90% band) | Confidence |
|---|---|---|---|---|---|
| Fastest | 87.9 min | 74.1 km | 91/100 | 10.99 (6.47-19.4) | Medium |
| Recommended | 93.2 min | 53.6 km | 58/100 | 3.92 (2.27-6.66) | Medium |

Decision: SWITCH (P(alternative truly safer) = 0.998). Predicted cut 64.3%, ground-truth cut 65.0%, +5.3 min.

Why the fastest route is risky:
- Segment 499 (NH, 2.0 km, 12% of route risk): 2.0 median openings/km (U-turn & wrong-side conflicts)
- Segment 449 (NH, 2.2 km, 12% of route risk): 1.3 median openings/km (U-turn & wrong-side conflicts); unlit stretch after dark; fleet hotspot #2: 22033 harsh brakes, 2433 near-misses
- Segment 234 (NH, 2.6 km, 9% of route risk): 2.2 median openings/km (U-turn & wrong-side conflicts); unlit stretch after dark; fleet hotspot #11: 20764 harsh brakes, 3295 near-misses

## Driver brief (template, EN)
Tonight's route avoids the NH stretch with fog and frequent median openings. Expect 5 extra minutes. Keep a 4-second following distance in fog, use low beam, and do not stop on the carriageway.

## ड्राइवर ब्रीफ (टेम्पलेट, हिंदी)
आज रात का रूट कोहरे और बार-बार मीडियन कट वाले NH हिस्से से बचता है। लगभग 5 मिनट ज़्यादा लगेंगे। कोहरे में आगे की गाड़ी से 4 सेकंड की दूरी रखें, लो-बीम का प्रयोग करें और सड़क पर गाड़ी न रोकें।