"""A simulated world for testing KrishiSense without hardware.

Everything is deterministic for a given seed, so a virtual station and the server
(running as separate processes) agree on what the weather was and what the
forecast said.

Time: simulation timestamps start at SIM_EPOCH (1 March 2026, 00:00 IST, the dry
pre-monsoon season when irrigation decisions matter most) and run faster than
real time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .agronomy import et0_hargreaves
from .weather import DayForecast

SIM_EPOCH = 1772303400.0  # 2026-03-01 00:00:00 +05:30
DAY = 86400.0


def sim_day(ts: float) -> int:
    return int((ts - SIM_EPOCH) // DAY)


def sim_hour(ts: float) -> float:
    return ((ts - SIM_EPOCH) % DAY) / 3600.0


@dataclass
class DayWeather:
    day: int
    rain_mm: float          # what actually falls (around 15:00)
    forecast_rain_mm: float  # what the forecast said the day before
    forecast_prob_pct: float
    t_min: float
    t_max: float
    et0_mm: float


class WeatherScenario:
    """Daily weather with imperfect forecasts. rain_chance is the share of rainy days."""

    def __init__(self, seed: int = 7, rain_chance: float = 0.15, lat: float = 20.39,
                 start_doy: int = 60):
        self.seed, self.rain_chance, self.lat, self.start_doy = seed, rain_chance, lat, start_doy
        self._cache: dict[int, DayWeather] = {}

    def day(self, d: int) -> DayWeather:
        if d in self._cache:
            return self._cache[d]
        rng = np.random.default_rng([self.seed, max(d, 0)])
        rains = rng.random() < self.rain_chance
        rain = float(rng.gamma(2.0, 9.0)) if rains else 0.0          # mean ~18 mm on rainy days
        # forecasts are usually right, sometimes miss or false-alarm
        if rains:
            prob = float(rng.uniform(60, 95)) if rng.random() > 0.15 else float(rng.uniform(10, 35))
            f_rain = rain * float(rng.uniform(0.6, 1.4))
        else:
            false_alarm = rng.random() < 0.08
            prob = float(rng.uniform(55, 80)) if false_alarm else float(rng.uniform(0, 25))
            f_rain = float(rng.uniform(8, 25)) if false_alarm else float(rng.uniform(0, 2))
        doy = self.start_doy + d
        season = math.sin(2 * math.pi * (doy - 80) / 365)        # warmer into April-May
        t_max = 33 + 4 * season + float(rng.normal(0, 1.2)) - (3 if rains else 0)
        t_min = 22 + 3 * season + float(rng.normal(0, 1.0))
        et0 = et0_hargreaves(t_min, t_max, self.lat, doy) * (0.75 if rains else 1.0)
        w = DayWeather(d, rain, f_rain, prob, t_min, t_max, et0)
        self._cache[d] = w
        return w

    def forecast(self, ts: float, days: int = 3) -> list[DayForecast]:
        d0 = sim_day(ts)
        out = []
        for d in range(d0, d0 + days):
            w = self.day(d)
            out.append(DayForecast(f"day {d}", w.forecast_rain_mm, w.forecast_prob_pct, w.et0_mm,
                                   w.t_max, w.t_min))
        return out
