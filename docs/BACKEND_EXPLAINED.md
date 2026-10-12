# How the Backend Works — AHU Predictive Maintenance

> A comprehensive engineering explainer of the predictive maintenance pipeline: physical degradation modeling, three-layer anomaly detection, criticality-weighted health scoring, vectorised fault diagnosis, Remaining Useful Life (RUL) curve fitting, and alert hysteresis.

---

## The Big Picture

The backend is a **digital twin of an Air Handling Unit (AHU)**. The machine is modeled as a component graph (supply/return fans, cooling/heating coils, filter bank, damper), with each component holding typed sensor points.

There are two completely independent halves:

1. **The Simulator** holds the ground truth. It generates physical sensor readings and injects faults that progress over time according to degradation physics.
2. **The Analytics Engine** never sees the ground truth. It observes only the raw readings and baseline statistical parameters ($\mu$, $\sigma$) for each sensor, inferring machine condition in real time.

On every simulation tick, the analytics pipeline answers five questions in sequence:

```
┌─────────┐     ┌─────────┐     ┌──────────┐     ┌─────────┐     ┌─────┐
│ 1 Detect│ ──► │2 Assess │ ──► │3 Diagnose│ ──► │4 Predict│ ──► │5 Act│
└─────────┘     └─────────┘     └──────────┘     └─────────┘     └─────┘
Is reading      How healthy     Which fault      How long        Should we
abnormal?       is each part?   fits pattern?    to failure?     alert?
```

---

## 0. Simulation Clock & Physical Degradation

Normal sensor readings are stochastic noise around an engineered mean. A fault introduces a latent degradation severity $s(t) \in [0, 1]$ that distorts related signals.

### Simulation Clock & Speed Acceleration
The engine executes at a base frequency ($1\text{ Hz}$). The user-facing speed multiplier accelerates both simulated time per tick and wall-clock tick execution:

```text
Δday_per_tick = speed / (tick_hz · 86400)
tick_interval = 1 / (tick_hz · speed)
```

- At $50\times$, the 90-day scenario completes in approximately 52 minutes of wall time (or ~3 minutes when fast-forwarding).
- **Clean Pre-roll Fast Forward:** On app startup, the simulation fast-forwards to `SIM_START_DAY` (day 25) with baseline burn-in. The pre-roll computes internal time steps independently without mutating `state.speed_multiplier`, keeping the UI speed selection highlight clean.
- **WebSocket Broadcast Throttling:** Throttled to an 8 Hz cap (`DISPLAY_HZ = 8`) to maintain smooth frontend 60 FPS rendering regardless of internal simulation velocity.

### Normal Operation Baseline
Each sensor reading is modeled as a rated mean with Gaussian noise, a daily thermal diurnal cycle, and intermittent electrical/mechanical spikes:

```text
x = N(μ, σ) + 0.5σ · sin(2π · sim_day) + rare_spike  (p = 0.5%, N(0, 2σ))
x_clipped = clip(x, min_valid, max_valid)
```

Baseline statistical profiles ($\mu$, $\sigma$, rated limits) are defined per sensor point in `twin/factory.py` according to industrial AHU equipment ratings.

### Physics-Based Fault Curves
When a fault begins at `onset_day`, its degradation severity $s(t)$ follows the underlying physics of that mechanical failure mode (where `t = sim_day - onset_day`):

| Fault Mode | Entity | Severity Curve $s(t)$ | Physical Rationale | Signal Effects at Full Severity ($s=1.0$) |
|---|---|---|---|---|
| **FM-1 Bearing Wear** | Return Fan | $\alpha(e^{\beta t} - 1)$<br>$\alpha=0.0008, \beta=0.130$ | Exponential fatigue spalling: micro-pitting creates vibration, accelerating contact damage. | Vibration $\times 2.80$ (+180% ISO 10816 Zone D), Bearing Temp +25 °C, Current $\times 1.08$, Acoustic $\times 1.40$ |
| **FM-2 Belt Slippage** | Supply Fan | $\gamma t^2$<br>$\gamma=0.0008$ | Quadratic friction wear: gradual tension loss followed by rapid thermal/elastic decay. | Vibration $\times 1.60$, Acoustic squeal $\times 1.25$, Fan Speed $\times 0.90$ (-10%), Current dips 15% then surges +40% |
| **FM-3 Coil Fouling** | Cooling Coil | $\delta t$<br>$\delta=0.022$ | Linear fouling resistance (biofilm and particulate scale per TEMA/ASHRAE). | Discharge Temp +4.0 °C, Coil $\Delta T \times 0.70$ (-30%), Power $\times 1.15$ (+15%) |
| **FM-4 Filter Clogging** | Filter Bank | $\epsilon t^{1.5}$<br>$\epsilon=0.018$ | Sub-exponential Darcy-Weisbach cake buildup as pores progressively choke. | Filter $\Delta P \times 3.0$ (120 Pa → 360 Pa, exceeding ASHRAE 250 Pa limit), Airflow $\times 0.80$ (-20%), Current $\times 1.12$ (+12%) |
| **FM-5 Damper Failure** | Mixing Damper | $t / 40.0$<br>(reaches $1.0$ at 40 d) | Actuator motor winding failure: positioning hysteresis transitioning to fixed stuck mechanical bind. | Mixed Air Temp $\pm 3s$ °C drift → stuck +8 °C offset past $s \ge 0.7$, Power $\times 1.25$ (+25%) |

---

## 1. Detection: Is This Reading Abnormal?

Simple z-score thresholds either suffer from high false alarm rates (if set tight) or miss gradual drift (if set loose). The pipeline combines three distinct detection layers per sensor:

### a) EWMA Residual (Sudden Departures)
An Exponentially Weighted Moving Average tracks short-term baseline shifts:
```text
e_t = α · x_t + (1 - α) · e_{t-1}    (α = 0.01, effective memory ≈ 100 samples)
score_EWMA = min(1.0, |x_t - e_t| / (3.0 · σ))
```

### b) Page's CUSUM (Persistent Small Shifts)
A two-sided Cumulative Sum accumulates evidence when the mean departs from baseline:
```text
S⁺ = max(0, S⁺ + (x - μ) - k)       where k = 1.0σ (slack allowance)
S⁻ = min(0, S⁻ + (x - μ) + k)
score_CUSUM = min(1.0, max(S⁺, |S⁻|) / h)  where h = 5.0σ (decision threshold)
```
For a persistent $2\sigma$ shift, CUSUM triggers in approximately $5 / (2 - 1) = 5$ samples, catching slow creep that EWMA would adapt to.

### c) Isolation Forest (Non-Gaussian Structural Outliers)
Trained on the initial 100 samples of baseline data (`MIN_TRAINING_SAMPLES = 100`). Configured with `n_jobs=1` to guarantee rock-solid stability in resource-constrained cloud containers (512MB RAM):
```text
score_IF = clip((median_train - score_samples(x)) / (1.5 · |median_train|), 0.0, 1.0)
```
*Performance Optimization:* During fast-forward pre-roll jumps, IF score evaluation is bypassed while training buffers continue collecting, accelerating startup by ~20×.

### Layer Fusion
The three layer scores are fused into a unified anomaly score:
```text
anomaly_score = clip(0.7 · max(EWMA, CUSUM) + 0.3 · IF, 0.0, 1.0)
signal_health = 1.0 - anomaly_score
```
A reading is flagged as anomalous if `anomaly_score > 0.5`.

---

## 2. Assessment: Health Roll-Up

Component health is computed by averaging its constituent sensor health scores. System-level AHU health is computed using an operational criticality-weighted sum:

```text
H_component = mean(signal_health_i)

H_AHU = Σ (w_i · H_component_i)
```

### Criticality Weights (ASHRAE Functional Hierarchy)
- **Supply Fan (`ahu-01.supplyFan`):** $0.35$ (total airflow delivery loss if down)
- **Cooling Coil (`ahu-01.coolingCoil`):** $0.20$ (comfort, humidity, and condensation control)
- **Filter Bank (`ahu-01.filterBank`):** $0.15$ (protects downstream coils and indoor air quality)
- **Return Fan (`ahu-01.returnFan`):** $0.15$ (building pressurization and return loop)
- **Heating Coil (`ahu-01.heatingCoil`):** $0.10$ (freeze protection and winter conditioning)
- **Damper (`ahu-01.damper`):** $0.05$ (fresh air / return air mixing ratio)

### Operating States
- **Normal:** Health $\ge 0.70$ (nominal green)
- **Warning:** $0.40 \le$ Health $< 0.70$ (degradation amber)
- **Critical:** Health $< 0.40$ (action required red)

---

## 3. Diagnosis: Which Fault Fits the Pattern?

Rather than classifying scalar values, diagnosis maps multi-signal deviation vectors to known physical failure signatures.

Each component produces an 8-dimensional z-score deviation vector:
```text
z = [(x_i - μ_i) / σ_i]
Dimension Order: [vibration, acoustic, temperature, current, ΔP, airflow, speed, power]
```

Fault modes are represented by expected directional signatures:
- **Bearing Wear:** `[+3.0, +1.5, +2.5, +0.8,  0.0,  0.0,  0.0,  0.0]` (vibration + temp dominant)
- **Belt Slippage:** `[+1.5, +2.5, +0.5, -1.0,  0.0, -1.0, -1.5, -0.8]` (acoustic squeal + RPM drop)
- **Filter Clogging:** `[ 0.0,  0.0,  0.0, +1.0, +3.0, -2.0,  0.0, +0.5]` (ΔP rise + airflow drop)
- **Coil Fouling:** `[ 0.0,  0.0, +2.0, +1.2,  0.0,  0.0,  0.0, +1.0]` (discharge temp rise + current)
- **Damper Failure:** `[ 0.0, +0.5, +1.5, +1.5,  0.0, +0.5,  0.0, +1.2]` (mixed temp offset + power)

### Cosine Similarity Matching
```text
confidence = max(0, cos(θ)) = max(0, (z · signature) / (‖z‖ · ‖signature‖))
```
- A fault is diagnosed if `confidence ≥ 0.45` ($\theta \le 63^\circ$) and vector magnitude $\|\mathbf{z}\| \ge 0.1$.
- **Why Cosine Similarity:** It evaluates deviation *direction* rather than magnitude. Early-stage wear and late-stage wear point in the same direction in feature space, enabling consistent diagnosis across the entire degradation curve.

---

## 4. Prediction: Remaining Useful Life (RUL)

RUL estimation activates once a component enters **Warning** state ($H \le 0.70$) and accumulates $\ge 30$ historical observations. It fits parametric degradation curves to the most recent 30% of health history:

1. **Exponential Decay:** $H(t) = a \cdot e^{bt} + c$ ($b \le 0$, bounds: $a \in [0,2], b \in [-5,0], c \in [0,1]$)
2. **Linear Decay:** $H(t) = mt + c$

Fitting is executed via `scipy.optimize.curve_fit`. The model with lower Mean Squared Error (MSE) is selected. The curve is projected forward in 0.5-day increments (up to 180 days) until crossing the functional failure line ($H < 0.15$):

```text
RUL_days = t_failure - t_current
```

The algorithm also computes projected lead time to the Critical boundary ($H = 0.40$) and Warning boundary ($H = 0.70$).

### Failure Probability
A continuous sigmoid function centered on the critical boundary ($H = 0.40$), amplified with an urgency penalty when RUL drops below 30 days:
```text
P_base = 1 / (1 + e^(6 · (H - 0.40)))
urgency_bump = 0.3 · (1 - RUL / 30)  if RUL < 30 days, else 0.0
P(fail) = clip(P_base + urgency_bump, 0.0, 1.0)
```
- At $H = 1.00$: $P \approx 3\%$ (nominal)
- At $H = 0.40$: $P \approx 50\%$ (critical boundary)
- At $H = 0.15$: $P \ge 82\%$ (functional failure)

---

## 5. Action: Alert Gating and Hysteresis

To prevent alert fatigue and false positives from transient spikes, alerts pass through a multi-stage gate:

1. **Training Gate:** Alerts suppressed for the first 20 simulation days (`sim_day < 20.0`) to establish baseline detector stability.
2. **Debounce:** Component must remain in Warning or Critical state for **5 consecutive ticks**.
3. **Edge Triggering:** Alerts fire strictly on state transitions (`normal → warning`, `warning → critical`), preventing duplicate notifications on every tick.
4. **Cooldown:** Enforces a minimum cooldown of **3 simulation days** between alerts on the same component.

### Actionable Maintenance Recommendations
When an alert is raised with a diagnosed fault mode, an actionable recommendation is generated with estimated maintenance downtime:
- **Bearing Wear:** Replace fan bearings (~4.0 hours downtime)
- **Belt Slippage:** Inspect and replace drive belt (~2.0 hours downtime)
- **Coil Fouling:** Chemical clean cooling coil (~6.0 hours downtime)
- **Filter Clogging:** Replace filter media (~0.5 hours downtime)
- **Damper Failure:** Inspect and recalibrate mixed air damper actuator (~3.0 hours downtime)

Recommendations are **sticky**: they persist in the UI until the component's health returns to Normal ($\ge 0.70$).

---

## 6. Headless Evaluation Benchmark

The repository includes a headless evaluation benchmark (`backend/evaluate.py`) that executes the 90-day simulation headlessly and checks analytics output against ground truth:

```bash
cd backend
python3 evaluate.py
```

### Benchmark Results
- **Detection Rate:** 100% (3/3 faults detected in advance of failure)
- **Diagnosis Accuracy:** 100% top-ranked matching
- **Lead Time Before Failure:**
  - Return Fan Bearing Wear: Detected at Day 37.3 (Lead time: 52.7 days before Day 90 failure)
  - Cooling Coil Fouling: Detected at Day 34.2 (Lead time: 55.8 days before Day 90 failure)
  - Filter Bank Clogging: Detected at Day 66.8 (Lead time: 23.2 days before Day 90 failure)
- **Mean Lead Time:** 43.9 days
- **False Alarm Count:** 0 false alerts during the 20-day baseline period.
