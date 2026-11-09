"""Synthetic field data so the whole pipeline can be demoed without hardware.

A simple bucket model: soil dries by ETc each day (faster at midday), rain and
irrigation refill it, and the probe raw values are produced through the station's
calibration in reverse, with sensor noise.
"""
from __future__ import annotations

import math

import numpy as np

from .agronomy import CROPS, SOILS
from .config import Station

STEP_S = 15 * 60


def simulate(station: Station, days: int = 7, start_ts: float = 1_730_000_000,
             start_available: float = 0.9, et0_mm: float = 4.5,
             rain_days: dict[int, float] | None = None, irrigate_days: dict[int, float] | None = None,
             seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    crop, soil = CROPS[station.crop], SOILS[station.soil]
    zr = crop.root_depth(station.stage)
    taw = 1000 * (soil.theta_fc - soil.theta_wp) * zr
    etc = crop.kc(station.stage) * et0_mm
    avail_mm = start_available * taw
    rain_days, irrigate_days = rain_days or {}, irrigate_days or {}
    out, seq = [], 0
    steps_per_day = 86400 // STEP_S
    for d in range(days):
        for s in range(steps_per_day):
            hour = s * STEP_S / 3600
            sun = max(0.0, math.sin(math.pi * (hour - 6) / 12))  # 6:00-18:00
            avail_mm -= etc * sun / (steps_per_day / math.pi)  # daily total = ETc
            if s == steps_per_day // 2 and d in rain_days:
                avail_mm += 0.8 * rain_days[d]
            if s == 7 * 4 and d in irrigate_days:  # 07:00
                avail_mm += irrigate_days[d]
            avail_mm = max(0.0, min(avail_mm, 1.1 * taw))
            frac = avail_mm / taw
            raws = []
            for i, cal in enumerate(station.probes):
                f = frac + (0.04 if i == 1 else 0.0)  # deeper soil stays slightly wetter
                raw = cal.raw_dry - f * (cal.raw_dry - cal.raw_field_capacity)
                raws.append(int(raw + rng.normal(0, 15)))
            t = 27 + 6 * math.sin(math.pi * (hour - 9) / 12) + rng.normal(0, 0.3)
            out.append({"seq": seq, "ts": start_ts + (d * steps_per_day + s) * STEP_S,
                        "soil_raw": raws, "air_temp_c": round(t, 1),
                        "humidity": round(75 - 15 * sun + rng.normal(0, 2), 1),
                        "pressure_hpa": 1006.0, "battery_v": round(4.1 - 0.002 * d, 2)})
            seq += 1
    return out
