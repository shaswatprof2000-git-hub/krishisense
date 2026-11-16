"""Tests for the software simulation: simulated weather, virtual stations, sim-mode server, dashboard."""
import threading
from collections import Counter

import pytest
import requests

from krishisense.notify import ConsoleNotifier
from krishisense.server import serve
from krishisense.service import Service
from krishisense.simworld import SIM_EPOCH, WeatherScenario, sim_day, sim_hour
from krishisense.store import Store
from krishisense.virtual_station import (HttpTransport, InProcessTransport, VirtualField, demo_fields,
                                         demo_stations, run)


class Quiet(ConsoleNotifier):
    def send(self, to, text):
        self.sent.append((to, text))
        return True


def make_service(tmp_path, seed=7):
    sc = WeatherScenario(seed)
    stations = demo_stations()
    svc = Service({s.station_id: s for s in stations}, Store(str(tmp_path / "sim.db")), Quiet(), scenario=sc)
    return svc, sc, stations


def test_weather_is_deterministic_and_forecasts_cover_three_days():
    a, b = WeatherScenario(3), WeatherScenario(3)
    assert [a.day(d).rain_mm for d in range(20)] == [b.day(d).rain_mm for d in range(20)]
    fc = a.forecast(SIM_EPOCH + 2.5 * 86400)
    assert len(fc) == 3 and fc[0].date == "day 2"
    assert sim_day(SIM_EPOCH + 86400 * 4 + 5) == 4 and sim_hour(SIM_EPOCH + 3600 * 7) == pytest.approx(7)
    assert all(1 < a.day(d).et0_mm < 9 for d in range(20))   # mm/day, Odisha dry season


def test_field_dries_without_water_and_recovers_with_irrigation(tmp_path):
    _, sc, stations = make_service(tmp_path)
    dry = WeatherScenario(1, rain_chance=0.0)
    f = VirtualField(stations[0], dry, start_fraction=0.9)
    start = f.avail
    for i in range(96):
        f.step(SIM_EPOCH + i * 900)
    assert f.avail < start                      # one day of crop water use
    used = start - f.avail
    assert 2 < used < 9                         # mm/day, plausible ETc
    before = f.avail
    f.irrigate(60)
    assert f.avail > before and f.pump_runs == 1


def test_closed_loop_simulation_in_process(tmp_path):
    svc, sc, stations = make_service(tmp_path)
    last = [0.0]

    def tick(ts, _):
        if ts - last[0] >= 3600:
            svc.check_all(ts)
            last[0] = ts

    report = {r["station"]: r for r in run(demo_fields(sc, stations), InProcessTransport(svc), days=10, on_tick=tick)}
    assert all(r["uploads"] > 900 for r in report.values())
    chilli = next(r for k, r in report.items() if k.startswith("Chilli"))
    assert chilli["max_buffered_readings"] > 40            # 12 h outage buffered, then flushed
    ground = next(r for k, r in report.items() if k.startswith("Groundnut"))
    assert ground["pump_runs"] >= 1                         # automatic pump control acted
    alerts = svc.store.alerts(limit=10000)
    statuses = Counter((a["station_id"], a["status"]) for a in alerts if a["recipient"].endswith("en"))
    assert statuses[("sim-chilli", "SENSOR_STALE")] >= 1    # the outage was noticed
    for (_, status), n in statuses.items():                 # no alert spam: at most ~1 per day per status
        assert n <= 11, (status, n)
    assert all(a["sent_at"] >= SIM_EPOCH for a in alerts)   # alerts carry simulated time


def test_sim_server_endpoints_and_dashboard(tmp_path):
    svc, sc, stations = make_service(tmp_path)
    httpd = serve(svc, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        run(demo_fields(sc, stations), HttpTransport(base), days=1.5)
        info = requests.get(base + "/api/v1/stations").json()
        assert info["simulated"] and len(info["stations"]) == 3
        assert info["clock"] == pytest.approx(SIM_EPOCH + 1.5 * 86400)
        hist = requests.get(base + "/api/v1/history", params={"station_id": "sim-tomato"}).json()
        assert len(hist) > 100 and 0 <= hist[-1]["water_pct"] <= 110
        assert requests.get(base + "/api/v1/alerts").status_code == 200
        assert requests.get(base + "/api/v1/pump", params={"station_id": "sim-groundnut"}).status_code == 200
        page = requests.get(base + "/")
        assert page.status_code == 200 and "KrishiSense" in page.text and "/api/v1/stations" in page.text
        assert requests.get(base + "/status").status_code == 200
    finally:
        httpd.shutdown()
