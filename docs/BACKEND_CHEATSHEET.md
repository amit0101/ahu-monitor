# Backend Core Cheatsheet

**Pipeline per tick:** `baseline sample → apply degradation → anomaly score → signal health → entity health → diagnosis → RUL → system health → alerts → recommendations`

## 1. Simulation clock — [engine.py](../backend/simulator/engine.py)
| Quantity | Formula | Default |
|---|---|---|
| Sim-time per tick | `Δday = speed / (tick_hz × 86400)` | 50× → 50 sim-s/tick |
| Wall time per tick | `1 / (tick_hz × speed)` | 20 ms |
| **Effective acceleration** | `speed² / tick_hz` sim-s per real-s | 50× → 2500× (≈ 0.029 d/s, 90 d ≈ 52 min) |
| Observer/WS rate | capped at `DISPLAY_HZ = 8` | analytics also runs at ≤ 8 Hz live |
| Pre-roll (Jump to day N) | speed = `1800 × tick_hz` → 30 sim-min/tick, no WS | day 25 ≈ 1 200 ticks |
| Speed bounds | `clamp(0.1, 500)`; mid pre-roll → `_pending_speed` | speed-down wait capped at 150 ms |

## 2. Baseline signal — [baseline.py](../backend/simulator/baseline.py)
`x = N(μ, σ) + 0.5σ·sin(2π·sim_day) + [0.5% chance: N(0, 2σ)]`, then `clip(min_valid, max_valid)`. μ, σ per sensor from [factory.py](../backend/twin/factory.py).

## 3. Degradation — [degradation.py](../backend/simulator/degradation.py)
`t = sim_day − onset`; `x' = x·factor + offset`; extra noise `N(0, σ·(noise_scale−1))`.

| Fault (entity, onset) | Severity `s(t)`, capped 1 | s = 1 at | Signal effects at s |
|---|---|---|---|
| FM-4 Filter clog (filterBank, d20) | `0.018·t^1.5` | ~14.6 d | ΔP ×(1+2s), airflow ×(1−0.2s), current ×(1+0.12s) |
| FM-1 Bearing wear (returnFan, d35) | `0.0008·(e^{0.13t} − 1)` | ~55 d | vib ×(1+1.8s), bearingTemp +25s °C, current ×(1+0.08s), acoustic ×(1+0.4s) |
| FM-3 Coil fouling (coolingCoil, d55) | `0.022·t` | ~45 d | dischargeTemp +4s °C, coilΔT ×(1−0.3s), power ×(1+0.15s) |
| FM-2 Belt slip (inject only) | `0.0008·t²` | ~35 d | vib ×(1+0.6s), speed ×(1−0.1s), current dips then rises past s=0.5 |
| FM-5 Damper (inject only) | `t / 40` | 40 d | mixedAirTemp ±3s random → stuck +8 °C past s=0.7, power ×(1+0.25s) |

## 4. Anomaly score per sensor — [anomaly.py](../backend/analytics/anomaly.py)
| Layer | Update | Score ∈ [0,1] |
|---|---|---|
| EWMA (α = 0.01) | `e ← αx + (1−α)e` | `|x − e| / 3σ` |
| CUSUM (k = 1σ, h = 5σ) | `S⁺ = max(0, S⁺ + (x−μ) − k)`, `S⁻ = min(0, S⁻ + (x−μ) + k)` | `max(S⁺, |S⁻|) / h` |
| Isolation Forest (50 trees, contam 0.05) | trains once after 100 samples, 1-D per sensor | `(median_train − raw) / (1.5·|median_train|)`, 0 while training or pre-rolling |

**Combined:** `score = clip(0.7·max(EWMA, CUSUM) + 0.3·IF)` · anomalous if `> 0.5` · `signal_health = 1 − score`

## 5. Health roll-up — [fusion.py](../backend/analytics/fusion.py)
- **Entity health** = plain mean of its signal healths.
- **System (ahu-01)** = weighted mean: supplyFan .35 · coolingCoil .20 · filter .15 · returnFan .15 · heatingCoil .10 · damper .05.
- **State:** `≥ 0.70` NORMAL · `≥ 0.40` WARNING · `< 0.40` CRITICAL.

## 6. Fault diagnosis — [diagnosis.py](../backend/analytics/diagnosis.py)
- `z_kind = (x − μ)/σ`, vector order `[vib, acoustic, temp, current, ΔP, airflow, speed]`.
- `conf = max(0, cos(z, signature))`, best of 5 signatures; diagnosed if `conf ≥ 0.45`; `‖z‖ < 0.1` → NONE.
- Signatures: bearing `[3, 1.5, 2.5, .8, 0, 0, 0]` · belt `[1.5, 2.5, .5, −1, 0, −1, −1.5]` · coil `[0, 0, 2, 1.2, 0, 0, 0]` · filter `[0, 0, 0, 1, 3, −2, 0]` · damper `[0, .5, 1.5, 1.5, 0, .5, 0]`.

## 7. RUL + failure probability — [prediction.py](../backend/analytics/prediction.py)
- Only runs when entity health `≤ 0.70` and has ≥ 30 history points; fits the most recent 30% of history.
- Fits `h = a·e^{bt} + c` (a∈[0,2], b∈[−5,0], c∈[0,1]) and `h = mt + c`; keeps the lower-MSE fit (exp needs a valid RUL; linear with `m ≥ 0` → no RUL).
- Projects in 0.5-day steps up to 180 d → **RUL** = first `h < 0.15`; also days to 0.70 / 0.40.
- **P(fail)** = `1 / (1 + e^{6(h − 0.4)})` (h=1 → 0.03, 0.4 → 0.50, 0.15 → 0.82); if RUL < 30 d add `0.3·(1 − RUL/30)`; clip at 1.

## 8. Alerts and recommendations — [fusion.py](../backend/analytics/fusion.py)
- **Alert fires when all hold:** sim_day ≥ 20 (training gate) · ≥ 5 consecutive degraded ticks · state ≠ last fired state (edge) · ≥ 3 sim-days since this entity's last alert. Back to NORMAL resets counter and edge.
- Lists capped: active 50, history 200.
- **Recommendations** are sticky per entity: raised on first WARNING/CRITICAL with a known fault, retired only on NORMAL. Priority: CRITICAL → `critical`; RUL < 15 d → `high`; WARNING → `medium`. Sorted by priority, then RUL.

## Known quirks (as coded)
- Acceleration is quadratic in `speed` (it scales both Δday and tick rate).
- IF training buffer only fills during **live** ticks (pre-roll skips `_iso_score`), so after a jump IF needs about 100 live observer calls (~12 s) to train. The buffer also keeps growing after training.
- Diagnosis keys z-scores by `SensorKind`, so multiple TEMPERATURE sensors overwrite each other (last one wins). POWER is not in the vector.
- `_failure_probability` docstring values (0.73 / 0.99) don't match the formula; the real values are in §7.
