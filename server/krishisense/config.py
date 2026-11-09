"""Station configuration, loaded from stations.json."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .agronomy import CROPS, IRRIGATION_EFFICIENCY, SOILS, STAGES


@dataclass
class ProbeCalibration:
    raw_dry: float = 3000.0             # reading at the dry / wilting point (higher = drier)
    raw_field_capacity: float = 1300.0  # reading ~24 h after a deep irrigation

    def available_fraction(self, raw: float) -> float:
        """0 = wilting point, 1 = field capacity (can exceed 1 just after irrigation)."""
        span = self.raw_dry - self.raw_field_capacity
        if span <= 0:
            raise ValueError("raw_dry must be greater than raw_field_capacity")
        return max(0.0, min(1.2, (self.raw_dry - raw) / span))


@dataclass
class Contact:
    name: str
    whatsapp: str            # international format without +, e.g. 9198xxxxxxxx
    language: str = "or"     # "or" Odia, "hi" Hindi, "en" English


@dataclass
class Station:
    station_id: str
    name: str
    device_key: str
    lat: float
    lon: float
    crop: str = "tomato"
    stage: str = "development"
    soil: str = "loam"
    area_m2: float = 1000.0
    pump_lpm: float = 300.0             # pump flow at the field, litres/minute
    irrigation_method: str = "furrow"
    probes: list[ProbeCalibration] = field(default_factory=lambda: [ProbeCalibration(), ProbeCalibration()])
    contacts: list[Contact] = field(default_factory=list)
    auto_pump: bool = False              # let the server command the pump relay
    max_pump_minutes: int = 60
    stale_after_hours: float = 3.0

    def __post_init__(self):
        if self.crop not in CROPS:
            raise ValueError(f"unknown crop {self.crop!r}; choose from {sorted(CROPS)}")
        if self.stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        if self.soil not in SOILS:
            raise ValueError(f"unknown soil {self.soil!r}; choose from {sorted(SOILS)}")
        if self.irrigation_method not in IRRIGATION_EFFICIENCY:
            raise ValueError(f"irrigation_method must be one of {sorted(IRRIGATION_EFFICIENCY)}")


def load_stations(path: str | Path) -> dict[str, Station]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for s in data["stations"]:
        s = dict(s)
        s["probes"] = [ProbeCalibration(**p) for p in s.get("probes", [{}, {}])]
        s["contacts"] = [Contact(**c) for c in s.get("contacts", [])]
        st = Station(**s)
        out[st.station_id] = st
    return out
