"""
twin/factory.py — Build the AHU-01 digital twin from engineering specs.

This is the single place that defines AHU-01's structure:
  AHU-01
  ├── Supply Fan (Motor, Belt, Bearings)
  ├── Return Fan (Motor, Bearings)
  ├── Cooling Coil
  ├── Heating Coil
  ├── Filter Bank
  └── Mixed Air Damper

Sensor baselines are grounded in real HVAC engineering data:
  - Vibration: ISO 10816-3 Zone A/B thresholds for medium machines
  - Temperature: typical AHU bearing operating temps
  - Current: 75% rated load typical for fans
  - Filter ΔP: ASHRAE 52.2 service interval guidance
"""
from __future__ import annotations

from .model import (
    TwinEntity, SensorPoint, SensorBaseline, SensorKind,
    OperatingState, HealthScore,
)
from .graph import DigitalTwinGraph


def build_ahu_01() -> DigitalTwinGraph:
    """Construct and return the fully populated AHU-01 digital twin graph."""
    graph = DigitalTwinGraph()

    # ── AHU Root ─────────────────────────────────────────────────────────────
    ahu = TwinEntity(
        id="ahu-01",
        dis="AHU-01 — Air Handling Unit",
        tags={"ahu", "equip", "hvac", "site:building-a", "floor:3"},
        parent_id=None,
        manufacturer="Carrier",
        model_number="AHF-048",
        install_date="2019-06-15",
        rated_power_kw=22.4,
    )
    graph.add_entity(ahu)

    # ── Supply Fan ───────────────────────────────────────────────────────────
    supply_fan = TwinEntity(
        id="ahu-01.supplyFan",
        dis="Supply Fan",
        tags={"fan", "equip", "supply", "hvac"},
        parent_id="ahu-01",
        rated_speed_rpm=1450,
        rated_power_kw=11.0,
    )
    supply_fan.add_point(SensorPoint(
        id="ahu-01.supplyFan.vibration",
        dis="Supply Fan Vibration",
        kind=SensorKind.VIBRATION,
        tags={"vibration", "sensor", "fan", "supply"},
        baseline=SensorBaseline(
            mean=2.8, std=0.3, unit="mm/s",
            min_valid=0.0, max_valid=50.0,
            warning_factor=1.8,   # 5.0 mm/s → ISO 10816 Zone C
            critical_factor=3.2,  # 9.0 mm/s → ISO 10816 Zone D
        ),
    ))
    supply_fan.add_point(SensorPoint(
        id="ahu-01.supplyFan.bearingTemp",
        dis="Supply Fan Bearing Temperature",
        kind=SensorKind.TEMPERATURE,
        tags={"temperature", "sensor", "bearing", "fan", "supply"},
        baseline=SensorBaseline(
            mean=45.0, std=2.0, unit="°C",
            min_valid=10.0, max_valid=120.0,
            warning_factor=1.33,  # ~60°C
            critical_factor=1.67, # ~75°C
        ),
    ))
    supply_fan.add_point(SensorPoint(
        id="ahu-01.supplyFan.current",
        dis="Supply Fan Motor Current",
        kind=SensorKind.CURRENT,
        tags={"current", "sensor", "motor", "fan", "supply"},
        baseline=SensorBaseline(
            mean=12.5, std=0.4, unit="A",
            min_valid=0.0, max_valid=40.0,
            warning_factor=1.2,
            critical_factor=1.4,
        ),
    ))
    supply_fan.add_point(SensorPoint(
        id="ahu-01.supplyFan.acoustic",
        dis="Supply Fan Acoustic SPL",
        kind=SensorKind.ACOUSTIC,
        tags={"acoustic", "sensor", "fan", "supply"},
        baseline=SensorBaseline(
            mean=72.0, std=1.5, unit="dBA",
            min_valid=40.0, max_valid=110.0,
            warning_factor=1.08,  # +6 dB (perceptually twice as loud)
            critical_factor=1.14, # +10 dB
        ),
    ))
    supply_fan.add_point(SensorPoint(
        id="ahu-01.supplyFan.speed",
        dis="Supply Fan Speed",
        kind=SensorKind.SPEED,
        tags={"speed", "sensor", "fan", "supply"},
        baseline=SensorBaseline(
            mean=1450.0, std=10.0, unit="RPM",
            min_valid=0.0, max_valid=2000.0,
            warning_factor=0.9,   # Note: drop below threshold is bad
            critical_factor=0.8,
        ),
    ))
    graph.add_entity(supply_fan)

    # ── Return Fan ───────────────────────────────────────────────────────────
    return_fan = TwinEntity(
        id="ahu-01.returnFan",
        dis="Return Fan",
        tags={"fan", "equip", "return", "hvac"},
        parent_id="ahu-01",
        rated_speed_rpm=1200,
        rated_power_kw=7.5,
    )
    return_fan.add_point(SensorPoint(
        id="ahu-01.returnFan.vibration",
        dis="Return Fan Vibration",
        kind=SensorKind.VIBRATION,
        tags={"vibration", "sensor", "fan", "return"},
        baseline=SensorBaseline(
            mean=2.8, std=0.3, unit="mm/s",
            min_valid=0.0, max_valid=50.0,
            warning_factor=1.8,
            critical_factor=3.2,
        ),
    ))
    return_fan.add_point(SensorPoint(
        id="ahu-01.returnFan.bearingTemp",
        dis="Return Fan Bearing Temperature",
        kind=SensorKind.TEMPERATURE,
        tags={"temperature", "sensor", "bearing", "fan", "return"},
        baseline=SensorBaseline(
            mean=45.0, std=2.0, unit="°C",
            min_valid=10.0, max_valid=120.0,
            warning_factor=1.33,
            critical_factor=1.67,
        ),
    ))
    return_fan.add_point(SensorPoint(
        id="ahu-01.returnFan.current",
        dis="Return Fan Motor Current",
        kind=SensorKind.CURRENT,
        tags={"current", "sensor", "motor", "fan", "return"},
        baseline=SensorBaseline(
            mean=9.0, std=0.3, unit="A",
            min_valid=0.0, max_valid=30.0,
            warning_factor=1.2,
            critical_factor=1.4,
        ),
    ))
    return_fan.add_point(SensorPoint(
        id="ahu-01.returnFan.acoustic",
        dis="Return Fan Acoustic SPL",
        kind=SensorKind.ACOUSTIC,
        tags={"acoustic", "sensor", "fan", "return"},
        baseline=SensorBaseline(
            mean=70.0, std=1.5, unit="dBA",
            min_valid=40.0, max_valid=110.0,
            warning_factor=1.08,
            critical_factor=1.14,
        ),
    ))
    graph.add_entity(return_fan)

    # ── Cooling Coil ─────────────────────────────────────────────────────────
    cooling_coil = TwinEntity(
        id="ahu-01.coolingCoil",
        dis="Cooling Coil",
        tags={"coil", "equip", "cooling", "hvac"},
        parent_id="ahu-01",
    )
    cooling_coil.add_point(SensorPoint(
        id="ahu-01.coolingCoil.dischargeTemp",
        dis="Discharge Air Temperature",
        kind=SensorKind.TEMPERATURE,
        tags={"temperature", "sensor", "air", "discharge"},
        baseline=SensorBaseline(
            mean=13.0, std=0.5, unit="°C",
            min_valid=-5.0, max_valid=40.0,
            warning_factor=1.38,  # +5°C above setpoint
            critical_factor=1.77, # +10°C above setpoint
        ),
    ))
    cooling_coil.add_point(SensorPoint(
        id="ahu-01.coolingCoil.coilDeltaT",
        dis="Coil Approach Temperature (ΔT)",
        kind=SensorKind.TEMPERATURE,
        tags={"temperature", "sensor", "coil", "delta"},
        baseline=SensorBaseline(
            mean=8.0, std=0.4, unit="°C",
            min_valid=0.0, max_valid=20.0,
            warning_factor=0.75,  # Drop below 6°C (fouling reduces effectiveness)
            critical_factor=0.50,
        ),
    ))
    cooling_coil.add_point(SensorPoint(
        id="ahu-01.coolingCoil.power",
        dis="Cooling Power Consumption",
        kind=SensorKind.POWER,
        tags={"power", "sensor", "cooling"},
        baseline=SensorBaseline(
            mean=14.0, std=0.8, unit="kW",
            min_valid=0.0, max_valid=50.0,
            warning_factor=1.2,
            critical_factor=1.4,
        ),
    ))
    graph.add_entity(cooling_coil)

    # ── Heating Coil ─────────────────────────────────────────────────────────
    heating_coil = TwinEntity(
        id="ahu-01.heatingCoil",
        dis="Heating Coil",
        tags={"coil", "equip", "heating", "hvac"},
        parent_id="ahu-01",
    )
    heating_coil.add_point(SensorPoint(
        id="ahu-01.heatingCoil.supplyTemp",
        dis="Heating Coil Supply Temperature",
        kind=SensorKind.TEMPERATURE,
        tags={"temperature", "sensor", "air", "supply", "heating"},
        baseline=SensorBaseline(
            mean=22.0, std=0.5, unit="°C",
            min_valid=0.0, max_valid=60.0,
            warning_factor=1.23,
            critical_factor=1.50,
        ),
    ))
    graph.add_entity(heating_coil)

    # ── Filter Bank ──────────────────────────────────────────────────────────
    filter_bank = TwinEntity(
        id="ahu-01.filterBank",
        dis="Filter Bank",
        tags={"filter", "equip", "hvac"},
        parent_id="ahu-01",
    )
    filter_bank.add_point(SensorPoint(
        id="ahu-01.filterBank.pressureDiff",
        dis="Filter Differential Pressure",
        kind=SensorKind.PRESSURE_DIFF,
        tags={"pressure", "sensor", "filter", "differential"},
        baseline=SensorBaseline(
            mean=120.0, std=8.0, unit="Pa",
            min_valid=0.0, max_valid=800.0,
            warning_factor=1.83,  # 220 Pa → ASHRAE recommended service
            critical_factor=2.50, # 300 Pa → urgent replacement
        ),
    ))
    filter_bank.add_point(SensorPoint(
        id="ahu-01.filterBank.airflow",
        dis="Supply Airflow",
        kind=SensorKind.AIRFLOW,
        tags={"airflow", "sensor", "supply"},
        baseline=SensorBaseline(
            mean=3600.0, std=80.0, unit="m³/h",
            min_valid=0.0, max_valid=6000.0,
            warning_factor=0.88,  # Drop to 3170 m³/h
            critical_factor=0.78, # Drop to 2800 m³/h
        ),
    ))
    graph.add_entity(filter_bank)

    # ── Mixed Air Damper ──────────────────────────────────────────────────────
    damper = TwinEntity(
        id="ahu-01.damper",
        dis="Mixed Air Damper",
        tags={"damper", "equip", "hvac", "mixed-air"},
        parent_id="ahu-01",
    )
    damper.add_point(SensorPoint(
        id="ahu-01.damper.mixedAirTemp",
        dis="Mixed Air Temperature",
        kind=SensorKind.TEMPERATURE,
        tags={"temperature", "sensor", "air", "mixed"},
        baseline=SensorBaseline(
            mean=18.0, std=0.8, unit="°C",
            min_valid=-10.0, max_valid=45.0,
            warning_factor=1.28,
            critical_factor=1.56,
        ),
    ))
    graph.add_entity(damper)

    return graph
