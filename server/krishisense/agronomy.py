"""Crop and soil water parameters plus reference evapotranspiration.

Values follow FAO Irrigation & Drainage Paper 56 (Allen et al., 1998): crop
coefficients Kc (Table 12), depletion fractions p (Table 22) and typical soil
water limits (Table 19). Root depths are set to the shallower end of FAO's
ranges because smallholder crops are often shallow-rooted. Tune them per field.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Crop:
    name: str
    kc_ini: float
    kc_mid: float
    kc_end: float
    root_depth_m: float   # mature effective root depth
    p: float              # fraction of available water usable before stress

    def kc(self, stage: str) -> float:
        return {"initial": self.kc_ini,
                "development": (self.kc_ini + self.kc_mid) / 2,
                "mid": self.kc_mid,
                "late": self.kc_end}[stage]

    def root_depth(self, stage: str) -> float:
        return self.root_depth_m * {"initial": 0.4, "development": 0.7, "mid": 1.0, "late": 1.0}[stage]


CROPS = {
    "tomato":    Crop("tomato",    0.60, 1.15, 0.80, 0.7, 0.40),
    "brinjal":   Crop("brinjal",   0.60, 1.05, 0.90, 0.7, 0.45),
    "chilli":    Crop("chilli",    0.60, 1.05, 0.90, 0.5, 0.30),
    "maize":     Crop("maize",     0.30, 1.20, 0.60, 1.0, 0.55),
    "groundnut": Crop("groundnut", 0.40, 1.15, 0.60, 0.5, 0.50),
    "cabbage":   Crop("cabbage",   0.70, 1.05, 0.95, 0.5, 0.45),
    "potato":    Crop("potato",    0.50, 1.15, 0.75, 0.4, 0.35),
    "watermelon": Crop("watermelon", 0.40, 1.00, 0.75, 0.8, 0.40),
}
STAGES = ("initial", "development", "mid", "late")


@dataclass(frozen=True)
class Soil:
    name: str
    theta_fc: float   # volumetric water content at field capacity (m3/m3)
    theta_wp: float   # at permanent wilting point


SOILS = {  # mid-points of FAO-56 Table 19 ranges
    "sandy":           Soil("sandy", 0.12, 0.05),
    "sandy_loam":      Soil("sandy_loam", 0.23, 0.11),
    "loam":            Soil("loam", 0.25, 0.12),
    "silty_clay_loam": Soil("silty_clay_loam", 0.33, 0.20),
    "clay":            Soil("clay", 0.36, 0.22),
}

# Fraction of pumped water that reaches the root zone
IRRIGATION_EFFICIENCY = {"drip": 0.90, "sprinkler": 0.75, "furrow": 0.60, "flood": 0.55}


def extraterrestrial_radiation_mm(lat_deg: float, day_of_year: int) -> float:
    """Ra expressed as equivalent evaporation (mm/day). FAO-56 eqs 21-25."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    ra_mj = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))
    return 0.408 * ra_mj


def et0_hargreaves(t_min: float, t_max: float, lat_deg: float, day_of_year: int) -> float:
    """Reference evapotranspiration (mm/day) from temperature only (FAO-56 eq 52).
    Used when the weather forecast is unavailable (offline mode)."""
    t_mean = (t_min + t_max) / 2
    ra = extraterrestrial_radiation_mm(lat_deg, day_of_year)
    return max(0.0, 0.0023 * (t_mean + 17.8) * math.sqrt(max(t_max - t_min, 0.0)) * ra)
