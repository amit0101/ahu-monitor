# Session Handoff — Aqueduct PdM POC

> Updated end of each session. Use with `START_PROMPT.md` for new chat.

## Last Updated
**Session 10 — 2026-10-12** (diagnosis fix, evaluation script, POC-to-production docs)

## Current State
All phases complete; app works end to end. Evaluation script validates analytics.

| Phase | Status |
|-------|--------|
| 1 Backend foundation | 31/31 tests |
| 2 Analytics engine | 31/31 tests |
| 3 Frontend dashboard | 0 TS errors |
| 4 3D visualization | Done |
| 5 Polish + docs | Docker, README, CI, ARCHITECTURE |
| 6 UI bug fixes | pause/resume, speed, throttle, layout |
| 7 E2E live test | 11/11 PASS (`e2e_test.py`) |
| 8 UI improvements | tsc clean; not re-run through e2e |
| 9 Speed UX + bell curves + cheatsheet | tsc clean |
| 10 Diagnosis fix + eval + prod docs | `evaluate.py` runs clean |

## Session 10 — Diagnosis Fix, Evaluation, Production Docs

### Bug fixes
- **Diagnosis multi-sensor bug** (`analytics/fusion.py`): `_compute_signal_deviations` now keeps
  the max-abs z-score when multiple sensors share a `SensorKind` (e.g. two TEMPERATURE points on
  the cooling coil). Previously the last one silently overwrote the first.
- **POWER added to diagnosis** (`analytics/diagnosis.py`): Added `SensorKind.POWER` as dimension 7
  to `SIGNAL_DIM_ORDER` and all 5 fault signatures. Coil fouling and damper failure now have
  non-zero power signatures.
- **P(fail) docstring** (`analytics/prediction.py`): Corrected the example values in
  `_failure_probability` docstring to match the actual sigmoid formula output.

### Evaluation script (`backend/evaluate.py`)
- Runs 90-day simulation headlessly at `speed_multiplier=3600` (1 tick = 1 hour → 2160 ticks, ~15s).
- Compares analytics output against ground truth: detection rate, lead time, diagnosis accuracy,
  false alarms.
- **Results (seed 42)**: 3/3 detected, 2/3 diagnosed correctly (coil fouling diagnosed `none` —
  onset too late for signature to develop), 9 false warnings (heatingCoil, damper, supplyFan —
  all WARNING, no CRITICAL), mean lead time 43.9 days.
- These are honest POC results; the false alarm rate shows where threshold tuning would focus next.

### Architecture docs
- **"From POC to Production" section** added to `docs/ARCHITECTURE.md` §8: 9-row table covering
  baselines, data rate, labelled faults, sensor drift, RUL uncertainty, multi-fault, persistence,
  scale, evaluation.

## Session 9 — Speed Control, Bell Curves, Docs
- **Speed down lag fixed (`simulator/engine.py` `_run`)**: sleeps in 50 ms chunks and recomputes
  the deadline. After a speed decrease, the extra wait is capped at 150 ms, so 50×→1× takes
  effect about as fast as 1×→50×.
- **Speed-change indicator (`Header.tsx`)**: clicking a speed dims the button and shows a pulsing dot.
  It clears when a WS snapshot arrives with `speed_multiplier === selectedSpeed`. A 2.5 s timeout
  is only a fallback. `speed_multiplier` was added to `get_live_snapshot()` and the `LiveSnapshot` type.
- **Bell curves (`SensorRow.tsx` `BellCurve`)**: 56×24 SVG Gaussian in the bottom-right of each
  sensor card, from baseline μ/σ, clipped to ±3.5σ. The vertical line marks the current value
  (dashed red if outside the range). Colors follow card health. The backend now sends
  `baseline_std` in `twin/model.py` `to_dict`, and the TS type has it too.
- **Docs**: [`docs/BACKEND_CHEATSHEET.md`](docs/BACKEND_CHEATSHEET.md) and HTML versions;
  [`docs/BACKEND_EXPLAINED.html`](docs/BACKEND_EXPLAINED.html) layered explainer.

## Earlier Sessions (brief)
- **S8 UI improvements**: light/dark toggle, 2D P&ID schematic, sim controls, jump-to presets.
- **S7 E2E**: Playwright script `e2e_test.py` → `E2E_REPORT.md` + `e2e_screenshots/`; 11/11 pass.
- **S6 fixes**: real pause/resume; optimistic speed; 8 Hz display throttle; CSS Grid layout.

## Start Commands
```bash
# Local dev
cd backend && python3 -m uvicorn main:app --reload --port 8000
cd frontend && npm run dev

# Docker (reviewer experience)
docker compose up --build
# → http://localhost:5173

# Run evaluation
cd backend && python3 evaluate.py
```

## What Remains (optional polish)
- [ ] Re-run/update `e2e_test.py` for new header + auto-start day 25
- [ ] README screenshot at ~day 50
- [ ] `useEffect` dependency lint warnings (cosmetic)
- [ ] Tune alert thresholds to reduce false alarm rate (currently 9 false WARNINGs)
- [ ] Coil fouling diagnosis doesn't converge with late onset — would need longer sim or faster signature buildup

## Invariants (do not break)
- Alert debounce: 5 consecutive ticks in WARNING/CRITICAL
- Alert cooldown: 3 sim-days minimum between alerts per entity
- Alert edge-trigger: fires only on state change (normal→warning, warning→critical)
- Alert training gate: no alerts before sim-day 20
- Palette: bg `#0C1A26` · blue `#0F7AC0` · amber `#E8890C` · green `#17A673` · red `#E84040`
