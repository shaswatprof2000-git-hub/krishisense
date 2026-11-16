"""Virtual field stations: a stand-in for the ESP32 hardware.

Each virtual station simulates its field (root-zone water balance driven by the
simulated weather, crop water use, rain and irrigation) and sends readings to
the server in exactly the JSON format the real firmware uses, every 15 simulated
minutes. It also simulates:
  * sensor noise and a slower-reacting deep probe
  * a solar-charged battery
  * network outages: readings are buffered and uploaded together afterwards,
    just like the firmware's RTC buffer
  * the farmer: in manual mode they check the advice at 07:00 and usually follow it
    (90% of the time); in auto mode the server's pump command runs the pump.

Run it against a live server (HTTP) or in-process (fast, for tests and reports).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from .advisor import IRRIGATE_NOW
from .agronomy import CROPS, IRRIGATION_EFFICIENCY, SOILS
from .config import Contact, ProbeCalibration, Station
from .simworld import SIM_EPOCH, WeatherScenario, sim_day, sim_hour

STEP_S = 15 * 60
BUFFER_MAX = 96  # same as the firmware


@dataclass
class Outage:
    start_ts: float
    end_ts: float


@dataclass
class VirtualField:
    station: Station
    scenario: WeatherScenario
    start_fraction: float = 0.8
    farmer_compliance: float = 0.9
    outages: list[Outage] = field(default_factory=list)
    seed: int = 0

    def __post_init__(self):
        crop, soil = CROPS[self.station.crop], SOILS[self.station.soil]
        self.taw = 1000 * (soil.theta_fc - soil.theta_wp) * crop.root_depth(self.station.stage)
        self.raw = crop.p * self.taw
        self.kc = crop.kc(self.station.stage)
        self.avail = self.start_fraction * self.taw
        self.deep_frac = self.start_fraction
        self.battery = 4.05
        self.rng = np.random.default_rng(self.seed)
        self.buffer: list[dict] = []
        self.seq = 0
        # running totals for the report
        self.water_litres = 0.0
        self.rain_mm = 0.0
        self.stress_hours = 0.0
        self.severe_hours = 0.0
        self.pump_runs = 0
        self.uploads = 0
        self.buffered_max = 0

    # ---- physics ---------------------------------------------------------------
    def step(self, ts: float, dt_s: float = STEP_S) -> None:
        """Advance the field from ts to ts + dt_s."""
        w = self.scenario.day(sim_day(ts))
        h = sim_hour(ts)
        dt_h = dt_s / 3600
        sun = max(0.0, math.sin(math.pi * (h - 6) / 12))
        etc_mm_per_h = (self.kc * w.et0_mm) / (24 / math.pi) * sun   # integrates to ETc over the day
        self.avail -= etc_mm_per_h * dt_h
        if 15.0 <= h < 16.0 and w.rain_mm > 0:                         # afternoon shower
            rain = 0.8 * w.rain_mm * dt_h                              # 80% soaks in
            self.avail += rain
            self.rain_mm += w.rain_mm * dt_h
        self.avail = min(max(self.avail, 0.0), 1.1 * self.taw)        # excess drains away
        depletion = self.taw - self.avail
        if depletion > self.raw:
            self.stress_hours += dt_h
        if depletion > 0.85 * self.taw:
            self.severe_hours += dt_h
        frac = self.avail / self.taw
        self.deep_frac += (frac - self.deep_frac) * min(1.0, dt_h / 6)  # deep probe lags ~6 h
        self.battery += (0.02 * sun - 0.004) * dt_h
        self.battery = min(4.15, max(3.2, self.battery))

    def irrigate(self, minutes: int) -> None:
        st = self.station
        litres = minutes * st.pump_lpm
        self.avail += litres * IRRIGATION_EFFICIENCY[st.irrigation_method] / st.area_m2
        self.avail = min(self.avail, 1.1 * self.taw)
        self.water_litres += litres
        self.pump_runs += 1

    # ---- what the firmware would send ---------------------------------------------
    def reading(self, ts: float) -> dict:
        w = self.scenario.day(sim_day(ts))
        h = sim_hour(ts)
        temp = w.t_min + (w.t_max - w.t_min) * (0.5 + 0.5 * math.sin(math.pi * (h - 9) / 12))
        raws = []
        for cal, f in zip(self.station.probes, (self.avail / self.taw, self.deep_frac)):
            raw = cal.raw_dry - f * (cal.raw_dry - cal.raw_field_capacity)
            raws.append(int(round(raw + self.rng.normal(0, 12))))
        r = {"seq": self.seq, "ts": ts, "soil_raw": raws, "air_temp_c": round(temp + self.rng.normal(0, 0.3), 1),
             "humidity": round(max(20, min(100, 85 - 1.6 * (temp - w.t_min) + self.rng.normal(0, 2))), 1),
             "pressure_hpa": round(1008 + self.rng.normal(0, 0.8), 1), "battery_v": round(self.battery, 2)}
        self.seq += 1
        return r

    def offline(self, ts: float) -> bool:
        return any(o.start_ts <= ts < o.end_ts for o in self.outages)

    def summary(self) -> dict:
        st = self.station
        return {"station": st.name, "crop": f"{st.crop} ({st.stage})", "soil": st.soil,
                "mode": "auto pump" if st.auto_pump else "farmer follows WhatsApp advice",
                "water_m3": round(self.water_litres / 1000, 1), "pump_runs": self.pump_runs,
                "rain_mm": round(self.rain_mm, 1), "stress_hours": round(self.stress_hours, 1),
                "severe_stress_hours": round(self.severe_hours, 1), "uploads": self.uploads,
                "max_buffered_readings": self.buffered_max}


# ---- transports -------------------------------------------------------------------
class InProcessTransport:
    """Talks to a Service object directly (fast, no network)."""

    def __init__(self, service):
        self.service = service

    def upload(self, station: Station, payload: dict) -> dict | None:
        return self.service.ingest(station, payload)

    def advice(self, station: Station) -> dict | None:
        return self.service.evaluate(station).to_dict()


class HttpTransport:
    """Talks to a running KrishiSense server exactly like the firmware does."""

    def __init__(self, base_url: str, timeout: float = 10.0):
        import requests
        self.base = base_url.rstrip("/")
        self.requests = requests
        self.timeout = timeout

    def upload(self, station: Station, payload: dict) -> dict | None:
        try:
            r = self.requests.post(f"{self.base}/api/v1/readings", json=payload, timeout=self.timeout,
                                   headers={"X-Device-Key": station.device_key})
            return r.json() if r.status_code == 200 else None
        except self.requests.RequestException:
            return None

    def advice(self, station: Station) -> dict | None:
        try:
            r = self.requests.get(f"{self.base}/api/v1/advice", params={"station_id": station.station_id},
                                  timeout=self.timeout)
            return r.json() if r.status_code == 200 else None
        except self.requests.RequestException:
            return None


# ---- the simulation loop -------------------------------------------------------------
def run(fields: list[VirtualField], transport, days: float = 14, speed: float | None = None,
        start_ts: float = SIM_EPOCH, on_tick=None) -> list[dict]:
    """Run all virtual stations together. speed = simulated seconds per real second
    (None = as fast as possible). Returns one summary dict per station."""
    ts = start_ts
    end = start_ts + days * 86400
    rng = np.random.default_rng(42)
    while ts < end:
        tick_started = time.time()
        for f in fields:
            f.step(ts)
        ts += STEP_S
        for f in fields:
            st = f.station
            f.buffer.append(f.reading(ts))
            f.buffer = f.buffer[-BUFFER_MAX:]
            f.buffered_max = max(f.buffered_max, len(f.buffer))
            if f.offline(ts):
                continue
            resp = transport.upload(st, {"station_id": st.station_id, "fw": "virtual-0.1",
                                         "readings": f.buffer})
            if resp is None:
                continue
            f.buffer = []
            f.uploads += 1
            pump = int(resp.get("command", {}).get("pump_minutes", 0) or 0)
            if st.auto_pump and pump > 0:
                f.irrigate(min(pump, st.max_pump_minutes))
            # manual farmer checks WhatsApp advice at 07:00
            if not st.auto_pump and abs(sim_hour(ts) - 7.0) < 1e-6:
                adv = transport.advice(st)
                if adv and adv.get("status") == IRRIGATE_NOW and rng.random() < f.farmer_compliance:
                    f.irrigate(int(adv["pump_minutes"]))
        if on_tick:
            on_tick(ts, fields)
        if speed:
            wait = STEP_S / speed - (time.time() - tick_started)
            if wait > 0:
                time.sleep(wait)
    return [f.summary() for f in fields]


def demo_stations() -> list[Station]:
    """Three illustrative fields near Phulnakhara (made-up settings, not real farms)."""
    contacts = [Contact("Farmer (Odia)", "SIMULATED-or", "or"), Contact("Supervisor (English)", "SIMULATED-en", "en")]
    cal = [ProbeCalibration(3000, 1300), ProbeCalibration(3000, 1300)]
    return [
        Station("sim-tomato", "Tomato plot (farmer follows advice)", "sim-key-1", 20.39, 85.86,
                crop="tomato", stage="mid", soil="loam", area_m2=1000, pump_lpm=300,
                irrigation_method="furrow", probes=cal, contacts=contacts),
        Station("sim-groundnut", "Groundnut plot (auto pump, drip)", "sim-key-2", 20.40, 85.87,
                crop="groundnut", stage="mid", soil="sandy_loam", area_m2=1500, pump_lpm=400,
                irrigation_method="drip", probes=cal, contacts=contacts, auto_pump=True, max_pump_minutes=150),
        Station("sim-chilli", "Chilli plot (network outage day 5)", "sim-key-3", 20.38, 85.85,
                crop="chilli", stage="development", soil="silty_clay_loam", area_m2=800, pump_lpm=250,
                irrigation_method="sprinkler", probes=cal, contacts=contacts),
    ]


def demo_fields(scenario: WeatherScenario, stations: list[Station] | None = None) -> list[VirtualField]:
    stations = stations or demo_stations()
    out = []
    for i, st in enumerate(stations):
        outages = [Outage(SIM_EPOCH + 4 * 86400 + 9 * 3600, SIM_EPOCH + 4 * 86400 + 21 * 3600)] \
            if st.station_id == "sim-chilli" else []
        out.append(VirtualField(st, scenario, start_fraction=[0.75, 0.7, 0.85][i % 3], outages=outages, seed=i))
    return out
