"""Irrigation decision engine: FAO-56 root-zone water balance + rain forecast.

1. Convert raw probe readings to soil water content (field calibration).
2. Root-zone depletion  Dr = 1000 * (theta_FC - theta) * Zr         [mm]
   Total available     TAW = 1000 * (theta_FC - theta_WP) * Zr      [mm]
   Readily available   RAW = p * TAW   (crop starts to stress beyond this)
3. If Dr >= RAW the crop needs water now. If forecast rain will cover most of
   it, skip. Otherwise refill to field capacity: net mm -> gross mm (method
   efficiency) -> litres (1 mm on 1 m2 = 1 L) -> pump minutes.
4. If today's crop water use (ETc = Kc * ET0) will push Dr past RAW within a
   day, warn: irrigate tomorrow morning.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from .agronomy import CROPS, IRRIGATION_EFFICIENCY, SOILS, et0_hargreaves
from .config import Station
from .weather import DayForecast

IRRIGATE_NOW = "IRRIGATE_NOW"
IRRIGATE_SOON = "IRRIGATE_SOON"
SKIP_RAIN = "SKIP_RAIN"
OK = "OK"
SENSOR_STALE = "SENSOR_STALE"
NO_DATA = "NO_DATA"

EFFECTIVE_RAIN_FACTOR = 0.8   # share of forecast rain that actually soaks in
RAIN_COVERS_SHARE = 0.6       # skip irrigation if expected rain covers >= 60% of the need


@dataclass
class Reading:
    ts: float                     # unix seconds
    soil_raw: list[float]
    air_temp_c: float | None = None
    humidity: float | None = None
    pressure_hpa: float | None = None
    battery_v: float | None = None


@dataclass
class Advice:
    station_id: str
    status: str
    pump_minutes: int = 0
    urgent: bool = False
    available_water_pct: float | None = None
    depletion_mm: float | None = None
    raw_mm: float | None = None
    taw_mm: float | None = None
    etc_mm_day: float | None = None
    rain_next_24h_mm: float = 0.0
    rain_prob_pct: float = 0.0
    hours_since_reading: float | None = None
    battery_v: float | None = None
    forecast_used: bool = False
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)


def soil_theta(station: Station, soil_raw: list[float]) -> float:
    """Volumetric water content of the root zone from the probes."""
    soil = SOILS[station.soil]
    fracs = [cal.available_fraction(raw) for cal, raw in zip(station.probes, soil_raw)]
    crop = CROPS[station.crop]
    if len(fracs) == 1:
        f = fracs[0]
    elif crop.root_depth(station.stage) <= 0.3:   # shallow roots: trust the top probe more
        f = 0.75 * fracs[0] + 0.25 * fracs[1]
    else:
        f = 0.5 * fracs[0] + 0.5 * fracs[1]
    return soil.theta_wp + f * (soil.theta_fc - soil.theta_wp)


def _round_minutes(m: float) -> int:
    if m <= 0:
        return 0
    return int(max(5, 5 * round(m / 5)))


def advise(station: Station, reading: Reading | None, forecast: list[DayForecast] | None,
           now: float | None = None, recent_temps: tuple[float, float] | None = None) -> Advice:
    now = now if now is not None else datetime.now().timestamp()
    if reading is None:
        return Advice(station.station_id, NO_DATA, notes=["no readings received yet"])

    hours = (now - reading.ts) / 3600
    adv = Advice(station.station_id, OK, hours_since_reading=round(hours, 1),
                 battery_v=reading.battery_v)
    if reading.battery_v is not None and reading.battery_v < 3.4:
        adv.notes.append(f"battery low ({reading.battery_v:.2f} V)")
    if hours > station.stale_after_hours:
        adv.status = SENSOR_STALE
        return adv

    crop, soil = CROPS[station.crop], SOILS[station.soil]
    zr = crop.root_depth(station.stage)
    theta = soil_theta(station, reading.soil_raw)
    taw = 1000 * (soil.theta_fc - soil.theta_wp) * zr
    dr = max(0.0, 1000 * (soil.theta_fc - theta) * zr)
    raw = crop.p * taw
    adv.taw_mm, adv.raw_mm, adv.depletion_mm = round(taw, 1), round(raw, 1), round(dr, 1)
    adv.available_water_pct = round(max(0.0, min(100.0, 100 * (1 - dr / taw))), 0)

    # Crop water use today
    doy = datetime.fromtimestamp(now).timetuple().tm_yday
    if forecast:
        adv.forecast_used = True
        today, tomorrow = forecast[0], (forecast[1] if len(forecast) > 1 else forecast[0])
        et0 = today.et0_mm or et0_hargreaves(today.t_min, today.t_max, station.lat, doy)
        adv.rain_next_24h_mm = round(today.rain_mm, 1)
        adv.rain_prob_pct = round(today.rain_prob_pct, 0)
    else:
        adv.notes.append("weather forecast unavailable: rain not considered")
        t_min, t_max = recent_temps if recent_temps else (24.0, 33.0)
        if t_max - t_min < 4.0:  # less than a day of data: assume a typical daily swing
            mid = (t_min + t_max) / 2
            t_min, t_max = mid - 4.5, mid + 4.5
        et0 = et0_hargreaves(t_min, t_max, station.lat, doy)
        tomorrow = None
    etc = crop.kc(station.stage) * et0
    adv.etc_mm_day = round(etc, 1)
    expected_rain = EFFECTIVE_RAIN_FACTOR * adv.rain_next_24h_mm * adv.rain_prob_pct / 100

    eff = IRRIGATION_EFFICIENCY[station.irrigation_method]

    def minutes_for(net_mm: float) -> int:
        litres = (net_mm / eff) * station.area_m2
        # Full requirement. The max_pump_minutes safety cap applies only to automatic
        # relay control (see service.pump_command), never to what the farmer is told.
        return _round_minutes(litres / station.pump_lpm)

    if dr >= raw:
        if expected_rain >= RAIN_COVERS_SHARE * dr:
            adv.status = SKIP_RAIN
            return adv
        adv.status = IRRIGATE_NOW
        adv.urgent = dr >= 0.85 * taw
        adv.pump_minutes = minutes_for(dr - expected_rain)
        if station.auto_pump and adv.pump_minutes > station.max_pump_minutes:
            adv.notes.append(f"auto-pump capped at {station.max_pump_minutes} min per run; "
                             "the rest follows on the next run")
        return adv

    if dr + etc - expected_rain >= raw:
        rain_tomorrow = 0.0
        if tomorrow is not None:
            rain_tomorrow = EFFECTIVE_RAIN_FACTOR * tomorrow.rain_mm * tomorrow.rain_prob_pct / 100
        projected = dr + etc - expected_rain
        if rain_tomorrow >= RAIN_COVERS_SHARE * projected:
            adv.notes.append("will need water soon, but rain is forecast tomorrow")
            return adv
        adv.status = IRRIGATE_SOON
        adv.pump_minutes = minutes_for(projected)
        return adv

    if etc > 0:
        days = (raw - dr) / etc
        adv.notes.append(f"about {days:.0f} day(s) until irrigation is needed")
    return adv
