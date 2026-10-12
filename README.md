# Aqueduct Predictive Maintenance POC

> **Built for Milvian Group / Aqueduct** — demonstrating credible predictive-maintenance engineering: physics-based simulation, multi-signal anomaly detection, fault diagnosis, and Remaining Useful Life estimation with a real-time 3D dashboard.

![Dashboard preview — AHU digital twin with live sensor telemetry, health gauges, and fault alerts](docs/dashboard_preview.png)

---

## ✨ What This Demonstrates

| Dimension | Approach |
|-----------|----------|
| **Asset model** | Graph-based digital twin with Haystack-inspired tagging — mirrors how real BMS/CMMS models work |
| **Sensor data** | Physics-based degradation simulation with 5 realistic HVAC fault modes (not random noise) |
| **Anomaly detection** | Three-layer: EWMA residual + CUSUM change detection + Isolation Forest (multi-variate) |
| **Fault diagnosis** | Cosine-similarity signature matching across multi-signal deviation vectors |
| **Prediction** | Exponential + linear RUL curve fitting via `scipy.optimize.curve_fit` |
| **3D visualization** | React Three Fiber scene with health-coded component colors + animated fan |
| **Domain alignment** | ISO 10816 vibration severity bands, ASHRAE maintenance language, Haystack tags |

---

## 🚀 Quick Start — Docker (recommended)

```bash
# 1. Clone
git clone https://github.com/your-username/aqueduct-assignment.git
cd aqueduct-assignment

# 2. (Optional) Set OpenAI key for the aQ Assistant chat panel
export OPENAI_API_KEY=sk-...

# 3. One-command startup
docker compose up --build
```

Open **http://localhost:5173** — the dashboard loads with the AHU in normal state and the simulation running at 50× speed.

> The `--build` flag is only needed on first run. Subsequent starts use `docker compose up`.

---

## 🛠 Local Development (without Docker)

### Backend

```bash
cd backend
pip install -r requirements.txt        # Python 3.11+
uvicorn main:app --reload --port 8000
```

API docs available at http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev                            # Vite dev server with HMR
```

Dashboard at http://localhost:5173 (Vite proxies `/api` and `/ws` to port 8000).

---

## 🎬 Demo Walkthrough

The simulation runs an **accelerated 90-day scenario** at 50× speed (≈ 3 minutes real time):

| Sim Day | Event |
|---------|-------|
| 0–20 | Normal operation — all components green, baseline telemetry |
| **~20** | 🟡 Filter bank ΔP begins rising (FM-4: filter clogging) |
| **~25** | First alert: *"Filter Bank health degrading"* — ΔP chart crosses 250 Pa reference line |
| **~35** | 🟡 Supply fan vibration begins exponential rise (FM-1: bearing wear) |
| **~42** | Bearing fault diagnosed: *"Probable cause: Bearing Wear (progressive)"* — RUL estimate appears |
| **~55** | 🔴 Coil fouling detected (FM-3) — concurrent fault test |
| **~65** | Supply fan health critical — RUL < 20 days |
| **~70** | Maintenance recommendation: *"Replace fan bearings — Priority: CRITICAL"* |

### Interactive Controls

- **Speed slider** — throttle from 1× to 100× in real time
- **Inject Fault** — manually trigger any of the 5 fault modes at the current sim day
- **Perform Maintenance** (restart) — resets the simulation to demonstrate recovery
- **aQ Assistant** — ask questions like *"What's wrong with the supply fan?"* (requires OpenAI key)
- **3D model** — click components to filter the sensor panel

---

## 🏗 Architecture

```
aqueduct-assignment/
├── backend/               FastAPI application
│   ├── twin/              Digital twin graph (Haystack-inspired entities)
│   ├── simulator/         Physics-based degradation engine (50× speed)
│   ├── analytics/         Anomaly detection, diagnosis, RUL estimation
│   └── api/               REST endpoints + WebSocket streaming
│
└── frontend/              React 18 + TypeScript dashboard
    └── src/
        ├── three/         React Three Fiber 3D AHU scene
        ├── components/    Dashboard panels (charts, health, alerts, maintenance)
        ├── hooks/         WebSocket + REST polling hooks
        └── stores/        Zustand global state
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a detailed system design narrative.

---

## 🧪 Tests

```bash
cd backend
pytest -v                              # 31 tests (14 degradation + 17 analytics)
```

All tests run in < 3 seconds. No mocking of the simulation engine — tests exercise real degradation curves and real anomaly detectors.

---

## ⚙️ Configuration

Key settings in `backend/.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `SIM_SPEED_MULTIPLIER` | `50` | Simulation acceleration (1–500×) |
| `SIM_AUTO_PLAY` | `true` | Start simulation on app boot, at `SIM_START_DAY` (default 25) |
| `OPENAI_API_KEY` | *(empty)* | For aQ Assistant LLM chat |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model selection |
| `EWMA_ALPHA` | `0.01` | EWMA smoothing factor (lower = slower to adapt) |
| `HEALTH_WARNING_THRESHOLD` | `0.70` | Health score → WARNING state |
| `HEALTH_CRITICAL_THRESHOLD` | `0.40` | Health score → CRITICAL state |

---

## 🔧 Tech Stack

| Layer | Technology | Why |
|-------|------------|-----|
| Backend | Python 3.11 + FastAPI | JD primary backend stack |
| Analytics | NumPy, SciPy, scikit-learn | Physics fits + Isolation Forest |
| Real-time | WebSocket (FastAPI native) | Live sensor streaming |
| Frontend | React 18 + TypeScript + Vite | JD primary frontend stack |
| State | Zustand | Lightweight, no boilerplate |
| Charts | Recharts | Composable React charting |
| 3D | React Three Fiber (Three.js) | JD: "3D digital twins" |
| Containers | Docker + docker-compose | One-command reviewer experience |
