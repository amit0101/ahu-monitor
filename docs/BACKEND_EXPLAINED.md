# How the Backend Works — AHU Predictive Maintenance

> A layered explanation of the predictive maintenance pipeline: physics-based simulation, anomaly detection, health scoring, fault diagnosis, Remaining Useful Life (RUL) estimation, and alert hysteresis.

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

## 0. Data Generation & Physical Degradation

Normal sensor readings are stochastic noise around an engineered mean. A fault introduces a latent degradation severity $s(t) \in [0, 1]$ that distorts related signals.

### Normal Operation Baseline
Each sensor reading is modeled as a rated mean with Gaussian noise, a daily thermal diurnal cycle, and intermittent electrical/mechanical spikes:

```text
x = N(μ, σ) + 0.5σ · sin(2π · sim_day) + rare_spike  (p = 0.5%, N(0, 2σ))
```

### Physics-Based Fault Curves
When a fault begins, its degradation severity follows the underlying physics of that mechanical failure mode:

| Fault Mode | Severity Curve $s(t)$ | Physical Rationale |
|---|---|---|
| **Bearing Wear** | $\alpha(e^{\beta t} - 1)$ | Exponential fatigue spalling: micro-pitting creates vibration, accelerating contact damage. |
| **Filter Clogging** | $\epsilon t^{1.5}$ | Non-linear dust cake buildup: airflow resistance increases faster than linear deposition. |
| **Coil Fouling** | $\delta t$ | Particulate and biofilm accumulation on fins: thermal resistance increases linearly. |
| **Belt Slippage** | $\gamma t^2$ | Quadratic friction wear: gradual tension loss followed by rapid thermal/elastic decay. |

Severity scales sensor readings according to each sensor's sensitivity factor $k$:
```text
x' = x · (1 + k · s) + offset · s
```
*Example (Bearing wear on return fan):* Vibration velocity scales by $\times(1 + 1.8s)$ and bearing temperature rises by $+25s$ °C.

---

## 1. Detection: Is This Reading Abnormal?

Simple z-score thresholds either suffer from high false alarm rates (if set tight) or miss gradual drift (if set loose). The pipeline combines three distinct detection layers per sensor:

### a) EWMA Residual (Sudden Departures)
An Exponentially Weighted Moving Average tracks short-term baseline shifts:
```text
e_t = 0.01 · x_t + 0.99 · e_{t-1}    (effective memory ≈ 100 samples)
score_EWMA = |x_t - e_t| / (3σ)
```

### b) Page's CUSUM (Persistent Small Shifts)
A two-sided Cumulative Sum accumulates evidence when the mean departs from baseline:
```text
S⁺ = max(0, S⁺ + (x - μ) - k)       where k = 1.0σ (slack)
S⁻ = min(0, S⁻ + (x - μ) + k)
score_CUSUM = max(S⁺, |S⁻|) / h     where h = 5.0σ (decision threshold)
```
For a persistent $2\sigma$ shift, CUSUM triggers in approximately $5 / (2 - 1) = 5$ samples, catching slow creep that EWMA would adapt to.

### c) Isolation Forest (Non-Gaussian Structural Outliers)
Trained on the initial 100 samples of baseline data. Points isolated with few partition splits receive higher anomaly scores, normalized against the median training score:
```text
score_IF = clip((inlier_median - score_samples(x)) / (spread · 3), 0, 1)
```

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

### Criticality Weights
- **Supply Fan:** $0.35$ (total airflow loss if down)
- **Cooling Coil:** $0.20$ (comfort and humidity control)
- **Filter Bank:** $0.15$ (protects coils and indoor air quality)
- **Return Fan:** $0.15$ (building pressurization)
- **Heating Coil:** $0.10$ (winter climate control)
- **Damper:** $0.05$ (fresh air mixing)

### Operating States
- **Normal:** Health $\ge 0.70$
- **Warning:** $0.40 \le$ Health $< 0.70$
- **Critical:** Health $< 0.40$

---

## 3. Diagnosis: Which Fault Fits the Pattern?

Rather than classifying scalar values, diagnosis maps multi-signal deviation vectors to known physical failure signatures.

Each component produces a 7-dimensional z-score deviation vector:
```text
z = [(x_i - μ_i) / σ_i]  for i ∈ [vibration, acoustic, temp, current, ΔP, airflow, speed]
```

Fault modes are represented by expected directional signatures:
- **Bearing Wear:** `[+3.0, +1.5, +2.5, +0.8,  0.0,  0.0,  0.0]` (vibration + temp dominant)
- **Filter Clogging:** `[ 0.0,  0.0,  0.0, +1.0, +3.0, -2.0,  0.0]` (ΔP rise + airflow drop)
- **Coil Fouling:** `[ 0.0,  0.0, +2.0, +1.2,  0.0,  0.0,  0.0]` (discharge temp rise + current)
- **Belt Slippage:** `[+1.5, +2.5, +0.5, -1.0,  0.0, -1.0, -1.5]` (acoustic squeal + RPM drop)

### Cosine Similarity Matching
```text
confidence = max(0, cos(θ)) = max(0, (z · signature) / (‖z‖ · ‖signature‖))
```
- A fault is diagnosed if `confidence ≥ 0.45` ($\theta \le 63^\circ$).
- **Why Cosine Similarity:** It evaluates deviation *direction* rather than magnitude. Early-stage wear and late-stage wear point in the same direction in feature space, enabling consistent diagnosis across severity levels.

---

## 4. Prediction: Remaining Useful Life (RUL)

RUL estimation activates once a component enters **Warning** state ($H \le 0.70$). It fits parametric degradation curves to the most recent 30% of health history:

1. **Exponential Decay:** $H(t) = a \cdot e^{bt} + c$ ($b \le 0$)
2. **Linear Decay:** $H(t) = mt + c$

The model with lower Mean Squared Error (MSE) is selected. The curve is projected forward in 0.5-day increments (up to 180 days) until crossing the functional failure line ($H < 0.15$):

```text
RUL_days = t_failure - t_current
```

### Failure Probability
A sigmoid function centered on the critical boundary ($H = 0.40$), amplified when RUL is short:
```text
P(fail) = 1 / (1 + e^(6 · (H - 0.40))) + urgency_bump

urgency_bump = 0.3 · (1 - RUL / 30)  if RUL < 30 days, else 0
```
- At $H = 1.0$: $P \approx 3\%$
- At $H = 0.40$: $P \approx 50\%$
- At $H = 0.15$: $P \ge 82\%$

---

## 5. Action: Alert Gating and Hysteresis

To prevent alert fatigue and false positives from transient spikes, alerts pass through a multi-stage gate:

1. **Training Gate:** Alerts suppressed for the first 20 simulation days to establish baseline stability.
2. **Debounce:** Component must remain in Warning or Critical state for **5 consecutive ticks**.
3. **Edge Triggering:** Alerts fire strictly on state transitions (`normal → warning`, `warning → critical`), not on every tick.
4. **Cooldown:** Enforces a minimum cooldown of **3 simulation days** between alerts on the same component.

Recommendations are raised alongside diagnosed alerts and remain active until component health recovers to Normal ($\ge 0.70$).

---

## Simulation Clock & Scaling

The engine executes at a configured tick frequency ($1\text{ Hz}$). The user-facing speed multiplier accelerates both simulated time per tick and wall-clock tick execution:

```text
Δday_per_tick = speed / (tick_hz · 86400)
tick_interval = 1 / (tick_hz · speed)
```
At $50\times$, the 90-day scenario completes in approximately 52 minutes of wall time (or ~3 minutes when fast-forwarding). WebSocket broadcasts are throttled to a readable 8 Hz cap regardless of internal calculation speed.
