"""Daily weather forecast from Open-Meteo (free, no API key).

Docs: https://open-meteo.com/en/docs . Results are cached for an hour; on any
network error the advisor falls back to sensor-based ET0 and assumes no rain.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

URL = "https://api.open-meteo.com/v1/forecast"
DAILY = ["precipitation_sum", "precipitation_probability_max", "et0_fao_evapotranspiration",
         "temperature_2m_max", "temperature_2m_min"]


@dataclass
class DayForecast:
    date: str
    rain_mm: float
    rain_prob_pct: float
    et0_mm: float
    t_max: float
    t_min: float


_cache: dict[tuple[float, float], tuple[float, list[DayForecast]]] = {}


def parse(payload: dict) -> list[DayForecast]:
    d = payload["daily"]
    out = []
    for i, date in enumerate(d["time"]):
        def g(key, default=0.0):
            v = d.get(key, [None] * len(d["time"]))[i]
            return default if v is None else float(v)
        out.append(DayForecast(date, g("precipitation_sum"), g("precipitation_probability_max", 50.0),
                               g("et0_fao_evapotranspiration"), g("temperature_2m_max"),
                               g("temperature_2m_min")))
    return out


def get_forecast(lat: float, lon: float, days: int = 3, timeout: float = 8.0,
                 cache_seconds: int = 3600) -> list[DayForecast] | None:
    key = (round(lat, 3), round(lon, 3))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < cache_seconds:
        return hit[1]
    try:
        r = requests.get(URL, params={"latitude": lat, "longitude": lon, "daily": ",".join(DAILY),
                                      "timezone": "Asia/Kolkata", "forecast_days": days},
                         timeout=timeout)
        r.raise_for_status()
        fc = parse(r.json())
    except Exception:
        return None
    _cache[key] = (time.time(), fc)
    return fc
