"""
config.py — Simulation and application configuration.
All tuneable parameters live here so nothing is hardcoded elsewhere.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────────
    app_title: str = "Aqueduct Predictive Maintenance API"
    app_version: str = "0.1.0"
    cors_origins: list[str] = ["*"]

    # ── Simulation ────────────────────────────────────────────────────────────
    sim_total_days: int = 90          # Scenario duration (sim-days)
    sim_tick_hz: float = 1.0          # Readings per sim-second (1 Hz sensor rate)
    sim_speed_multiplier: float = 50.0  # Wall-clock acceleration (50x default)
    sim_auto_play: bool = True        # Boot straight into a live run
    sim_start_day: int = 25           # ...at day 25 (filter clogging underway)

    # ── Baseline scenario events (sim-days) ──────────────────────────────────
    fault_filter_start_day: int = 20   # FM-4: filter clogging begins
    fault_bearing_start_day: int = 35  # FM-1: bearing degradation begins
    fault_coil_start_day: int = 55     # FM-3: coil fouling begins

    # ── Analytics ─────────────────────────────────────────────────────────────
    ewma_alpha: float = 0.01           # Slow-adapting EWMA (α=0.01)
    isolation_forest_contamination: float = 0.05
    baseline_training_days: int = 20   # Days of normal data before training IF
    rul_history_fraction: float = 0.30  # Fraction of data used for RUL curve fit
    health_warning_threshold: float = 0.70
    health_critical_threshold: float = 0.40

    # ── OpenAI ───────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ── Component health weights (must sum to 1.0) ────────────────────────────
    weight_supply_fan: float = 0.35
    weight_cooling_coil: float = 0.20
    weight_filter: float = 0.15
    weight_return_fan: float = 0.15
    weight_heating_coil: float = 0.10
    weight_damper: float = 0.05


settings = Settings()
