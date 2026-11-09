"""Glue: ingest uploads, run the advisor, decide on alerts and pump commands."""
from __future__ import annotations

import time

from . import weather
from .advisor import IRRIGATE_NOW, IRRIGATE_SOON, OK, SENSOR_STALE, SKIP_RAIN, Advice, advise
from .config import Station
from .messages import render
from .notify import Notifier
from .store import Store

ALERT_ON_CHANGE = {IRRIGATE_NOW, IRRIGATE_SOON, SKIP_RAIN, SENSOR_STALE}
REPEAT_AFTER_S = 20 * 3600          # repeat an unchanged warning at most ~daily
MIN_PUMP_GAP_S = 12 * 3600          # never auto-run the pump twice within 12 h


class Service:
    def __init__(self, stations: dict[str, Station], store: Store, notifier: Notifier,
                 forecast_fn=weather.get_forecast):
        self.stations, self.store, self.notifier = stations, store, notifier
        self.forecast_fn = forecast_fn

    def evaluate(self, station: Station, now: float | None = None) -> Advice:
        now = now or time.time()
        reading = self.store.latest_reading(station.station_id)
        forecast = self.forecast_fn(station.lat, station.lon)
        temps = self.store.temp_range(station.station_id, now - 24 * 3600)
        adv = advise(station, reading, forecast, now=now, recent_temps=temps)
        self.store.save_advice(adv)
        return adv

    def ingest(self, station: Station, payload: dict, now: float | None = None) -> dict:
        now = now or time.time()
        added = 0
        for r in payload.get("readings", []):
            if not r.get("ts"):
                r["ts"] = now
            if not isinstance(r.get("soil_raw"), list) or not r["soil_raw"]:
                continue
            added += self.store.add_reading(station.station_id, r)
        adv = self.evaluate(station, now)
        self.maybe_alert(station, adv, now)
        pump = self.pump_command(station, adv, now)
        return {"ok": True, "stored": added, "status": adv.status, "command": {"pump_minutes": pump}}

    def pump_command(self, station: Station, adv: Advice, now: float) -> int:
        if not station.auto_pump or adv.status != IRRIGATE_NOW or adv.pump_minutes <= 0:
            return 0
        last = self.store.last_pump_command(station.station_id)
        if last is not None and now - last < MIN_PUMP_GAP_S:
            return 0
        minutes = min(adv.pump_minutes, station.max_pump_minutes)
        self.store.log_pump_command(station.station_id, minutes)
        return minutes

    def maybe_alert(self, station: Station, adv: Advice, now: float, force: bool = False) -> int:
        if not force:
            if adv.status not in ALERT_ON_CHANGE:
                return 0
            last = self.store.last_alert(station.station_id)
            if last is not None and last["status"] == adv.status and now - last["sent_at"] < REPEAT_AFTER_S:
                return 0
        sent = 0
        for c in station.contacts:
            text = render(adv, station.name, c.language)
            if self.notifier.send(c.whatsapp, text):
                self.store.log_alert(station.station_id, adv.status, c.whatsapp, text)
                sent += 1
        return sent

    def daily_advisory(self, now: float | None = None) -> dict[str, Advice]:
        """Morning message to every contact, including 'all fine' days."""
        now = now or time.time()
        out = {}
        for st in self.stations.values():
            adv = self.evaluate(st, now)
            self.maybe_alert(st, adv, now, force=True)
            out[st.station_id] = adv
        return out

    def check_all(self, now: float | None = None) -> dict[str, Advice]:
        """Hourly check: catches stations that went silent (no uploads -> no ingest)."""
        now = now or time.time()
        out = {}
        for st in self.stations.values():
            adv = self.evaluate(st, now)
            if adv.status != OK:
                self.maybe_alert(st, adv, now)
            out[st.station_id] = adv
        return out
