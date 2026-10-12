# Architecture — AHU Predictive Maintenance Digital Twin

> This document explains the system design decisions and engineering rationale behind each layer of the platform.

---

## 1. System Overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Backend (Python / FastAPI)                                        │
│                                                                    │
│  ┌───────────┐    readings    ┌──────────────┐                    │
│  │ Simulator │ ─────────────► │ Digital Twin │                    │
│  │  Engine   │                │    Graph     │                    │
│  └───────────┘                └──────┬───────┘                    │
│       │ observer callback            │ entities + points          │
│       ▼                              ▼                            │
│  ┌───────────────────────────────────────────────────────┐        │
│  │  Analytics Engine (fusion.py)                         │        │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐            │        │
│  │  │  Anomaly │  │ Diagnoser│  │   RUL    │            │        │
│  │  │ Detector │  │(cosine   │  │Estimator │            │        │
│  │  │EWMA/CUSUM│  │similarity│  │(exp fit) │            │        │
│  │  │    /IF   │  │)         │  │          │            │        │
│  │  └──────────┘  └──────────┘  └──────────┘            │        │
│  └──────────────────────┬────────────────────────────────┘        │
│                         │ health scores, alerts, recs             │
│  ┌──────────┐           ▼                                         │
│  │ REST API │◄─── FastAPI routes ──► WebSocket broadcaster        │
│  └──────────┘                               │                     │
└────────────────────────────────────────────│────────────────────┘
                                              │ JSON over WS
┌────────────────────────────────────────────▼────────────────────┐
│  Frontend (React 18 / TypeScript)                                │
│                                                                  │
│  Zustand Store ◄── useWebSocket hook ◄── ws://localhost/ws/live  │
│       │                                                          │
│       ├── 3D AHU Scene (React Three Fiber)                      │
│       ├── Sensor gauge rows                                      │
│       ├── Time-series charts (Recharts) ◄── REST history polling │
│       ├── Health + RUL panel                                     │
│       ├── Alerts panel                                           │
│       ├── Maintenance recommendations panel                      │
│       └── aQ Assistant (OpenAI GPT-4o-mini)                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Digital Twin Design

### 2.1 Entity Graph

The twin is modelled as a directed acyclic graph of `TwinEntity` nodes:

```
AHU-01
├── Supply Fan
│   ├── Supply Fan Motor
│   ├── Supply Fan Belt
│   └── Supply Fan Bearings
├── Return Fan
│   ├── Return Fan Motor
│   └── Return Fan Bearings
├── Cooling Coil
├── Heating Coil
├── Mixed Air Damper
└── Filter Bank
```

Each entity carries:
- **Haystack-inspired tags**: `{ahu, equip, fan, supply, motor, …}` — semantic metadata standard for modern BMS/CMMS models.
- **Sensor points**: typed (`SensorKind`), with baseline distribution parameters drawn from real HVAC engineering data.
- **Health score**: rolled up from signal → component → system level.

### 2.2 Health Roll-up

```
signal_health  = 1 − anomaly_score          (per sensor point)
entity_health  = mean(signal_healths)       (unweighted within entity)
system_health  = Σ(weight_i × entity_i)    (weighted across components)
```

Component weights reflect operational criticality:

| Component | Weight |
|-----------|--------|
| Supply Fan | 0.35 |
| Cooling Coil | 0.20 |
| Filter Bank | 0.15 |
| Return Fan | 0.15 |
| Heating Coil | 0.10 |
| Damper | 0.05 |

---

## 3. Physics-Based Simulation

Instead of random noise + static thresholds, each fault mode follows a **physics-derived degradation curve** that produces realistic multi-signal correlations.

### Fault Mode Catalogue

| ID | Fault | Degradation Law | Key Signals |
|----|-------|----------------|-------------|
| FM-1 | Fan Bearing Wear | Exponential `e^(β·t)` | Vibration ↑ 180%, Bearing temp ↑ 25°C |
| FM-2 | Belt Slippage | Quadratic `γ·t²` | Acoustic ↑ (tonal), Speed ↓ 10% |
| FM-3 | Coil Fouling | Linear `δ·t` | Discharge temp ↑ 4°C, Coil ΔT ↓ 30% |
| FM-4 | Filter Clogging | Sub-exponential `ε·t^1.5` | Filter ΔP ↑ 200%, Airflow ↓ 20% |
| FM-5 | Damper Failure | Random drift → stuck | Mixed-air temp erratic |

**Engineering basis**: Vibration thresholds from ISO 10816; filter ΔP limits from ASHRAE 62.1; bearing temperature from standard industrial bearing specs.

### 90-Day Overlapping Scenario

```
Day  0 ──── 20 ────────── 35 ──────────── 55 ─────────── 75 ─── 90
      Normal   FM-4 begins   FM-1 begins     FM-3 begins   FM-1 critical
```

The overlapping timeline deliberately tests the system's ability to **disentangle concurrent faults** — a key requirement in real predictive maintenance.

---

## 4. Analytics Engine

### 4.1 Three-Layer Anomaly Detection (`anomaly.py`)

Each sensor maintains its own `DetectorState` (independent state per sensor):

**Layer 1 — EWMA Residual** (slow-adapting, α=0.01)
```
ewma_t = α·x_t + (1-α)·ewma_{t-1}
score  = |x_t - ewma_t| / (3σ)
```
Catches **monotonic drift** that static thresholds miss — the sensor gradually moves away from its expected value.

**Layer 2 — CUSUM** (persistent mean-shift detection)
```
S_pos = max(0, S_pos + (x - μ - k))
S_neg = min(0, S_neg + (x - μ + k))
score = max(S_pos, |S_neg|) / h
```
`k = 1σ` (allowable slack), `h = 5σ` (decision threshold). CUSUM accumulates small consistent deviations that EWMA alone would discount.

**Layer 3 — Isolation Forest** (multivariate; trains on first 100 readings)
- Trains on the clean baseline window (before any fault onset).
- Score calibrated to the median training-set score so normal readings produce ~0.0.
- Added weight 30% in final blend; EWMA/CUSUM carry 70%.

**Combined score**: `0.7 × max(ewma, cusum) + 0.3 × iso`

### 4.2 Fault Diagnosis (`diagnosis.py`)

Each fault mode has a **signature vector** of expected normalised deviations per signal type:

```python
FAULT_SIGNATURES = {
    FaultMode.BEARING_WEAR:    [+3.0, +1.5, +2.5, +0.8, 0.0, 0.0, 0.0],
    FaultMode.FILTER_CLOGGING: [ 0.0,  0.0,  0.0, +1.0, +3.0, -2.0, 0.0],
    # ... etc
}
# Dimensions: [vibration, acoustic, temp, current, filter_dp, airflow, speed]
```

Diagnosis is **cosine similarity** between the observed deviation vector and each fault signature — a normalised, magnitude-invariant comparison. Bearing wear (high vibration, zero ΔP) and filter clogging (zero vibration, high ΔP) are clearly separated in this space.

### 4.3 RUL Estimation (`prediction.py`)

Uses `scipy.optimize.curve_fit` on the most recent 30% of health history:

1. **Exponential fit**: `h(t) = a·e^(b·t) + c` — appropriate for bearing wear (accelerating failure)
2. **Linear fit**: `h(t) = m·t + c` — appropriate for fouling (steady-state accumulation)

The model with lower MSE residual is selected. The dashboard shows both fits alongside each other — demonstrating why naive linear extrapolation **underestimates risk** for accelerating faults.

**Failure probability** uses a sigmoid function:
```
P(failure) = σ(6·(0.4 − health))
```
This produces ~2% at health=1.0, ~73% at health=0.4, ~99% at health=0.15.

---

## 5. Real-Time Data Flow

```
Simulator tick (every 20ms at 50× speed)
    │
    ├─► AnalyticsEngine.on_tick()
    │       - Per-sensor anomaly scores updated
    │       - Entity health scores computed
    │       - System health rolled up
    │       - Alert transitions checked
    │       - Maintenance recommendations rebuilt
    │
    └─► broadcast_observer()
            - Snapshot captures already-updated health scores
            - asyncio.create_task(manager.broadcast_live(snapshot))
            - WebSocket message sent to all connected clients
```

The observer order matters: **analytics runs before broadcast**, so every WebSocket frame carries the latest anomaly scores and health values — not one tick stale.

---

## 6. WebSocket Protocol

Live frame structure (sent every simulator tick):

```json
{
  "sim_day": 42.17,
  "tick": 3641,
  "sensors": {
    "ahu-01.supplyFan.vibration": { "v": 4.82, "anom": true, "score": 0.71, "health": 0.29, "day": 42.17 },
    "ahu-01.filterBank.pressureDiff": { "v": 218.3, "anom": false, "score": 0.18, "health": 0.82, "day": 42.17 }
  },
  "health": {
    "ahu-01": { "health": 0.68, "state": "warning", "fault": "bearing_wear", "rul_days": 28.4 },
    "ahu-01.supplyFan": { "health": 0.41, "state": "warning", "fault": "bearing_wear", "rul_days": 28.4 }
  }
}
```

The frontend Zustand store processes this in `useWebSocket.ts` with exponential-backoff reconnection.

---

## 7. Design Decisions & Tradeoffs

| Decision | Rationale | Tradeoff |
|----------|-----------|----------|
| In-memory history buffer (5000 readings/sensor) | Zero dependency, fast | Resets on restart; a real system would use TimescaleDB or InfluxDB |
| Isolation Forest trained once on baseline | Simple, effective for POC | Won't re-adapt if baseline drifts; production would use streaming IF |
| Cosine similarity diagnosis | Magnitude-invariant, handles partial fault expression | Doesn't handle correlated fault modes (would use Bayesian network in prod) |
| Single FastAPI worker | Simpler for POC | Would need gunicorn + multiple workers in production |
| React Three Fiber procedural geometry | No GLTF pipeline needed | Less realistic than CAD-based model |

## 8. From POC to Production

This project is a simulation. A real BMS deployment differs in several ways that would affect the architecture. This section documents those gaps honestly — not to apologise for the POC, but to show they are understood.

| Concern | POC approach | What production would need |
|---------|-------------|---------------------------|
| **Baselines** | Fixed μ, σ per sensor from engineering specs | Learn per-asset baselines from commissioning data; re-learn when operating mode changes (e.g. night setback, economiser switchover). A simple approach: cluster operating modes by OA temp and fan speed, fit a separate N(μ, σ) per mode |
| **Data rate** | 1 Hz simulated, always available | Real BMS points arrive every 1–15 min via BACnet/Modbus. EWMA α and CUSUM slack would need re-tuning for the slower rate. Missing readings need interpolation or gap-aware accumulators |
| **Labelled faults** | Simulator provides exact ground truth | Real buildings have few labelled faults. Would need semi-supervised learning (e.g. anomaly clustering) or transfer learning from similar sites. The cosine-similarity diagnosis is useful here because the signatures come from physics, not training data |
| **Sensor drift** | Sensors are perfectly calibrated | Real sensors drift. A slow drift in a thermocouple looks like coil fouling. Would need drift detection (e.g. compare redundant sensors, or flag monotonic EWMA trend with no CUSUM alarm) |
| **RUL uncertainty** | Point estimate from curve_fit | curve_fit returns a covariance matrix. Production should report RUL as a confidence interval: "15–30 days (80% CI)" rather than a single number. The POC has the covariance available — just not surfaced |
| **Multi-fault interaction** | Faults contribute independently | Real faults can mask each other (e.g. a clogged filter reduces airflow, which cools bearings and delays bearing-temp rise). The diagnosis step would need a factor graph or Bayesian network to reason about interactions |
| **Persistence** | In-memory, resets on restart | Time-series in InfluxDB/TimescaleDB; health history and alerts in Postgres; trained IF models serialised to disk |
| **Scale** | 1 AHU, 15 sensors | A campus may have 200 AHUs × 15 sensors = 3 000 points. The analytics are per-sensor and embarrassingly parallel — a worker pool or Celery queue would handle this |
| **Evaluation** | `evaluate.py` runs offline against one scenario | A/B testing on historical fault records; track precision/recall/lead-time on a validation set of known incidents; alert fatigue metrics from operator feedback |

