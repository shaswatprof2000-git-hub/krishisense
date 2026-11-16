import json
import threading
import time

import pytest
import requests

from krishisense.advisor import (IRRIGATE_NOW, IRRIGATE_SOON, NO_DATA, OK, SENSOR_STALE, SKIP_RAIN,
                                 Reading, advise)
from krishisense.agronomy import CROPS, SOILS, et0_hargreaves
from krishisense.config import Contact, ProbeCalibration, Station, load_stations
from krishisense.messages import TEMPLATES, render
from krishisense.notify import ConsoleNotifier
from krishisense.server import serve
from krishisense.service import Service
from krishisense.simulate import simulate
from krishisense.store import Store
from krishisense.weather import DayForecast, parse

NOW = 1_730_000_000.0
DRY = DayForecast("d0", 0.0, 5, 4.8, 33, 25)
WET = DayForecast("d1", 30.0, 90, 3.0, 29, 24)


def station(**kw):
    base = dict(station_id="s1", name="Test Field", device_key="secret", lat=20.39, lon=85.86,
                crop="tomato", stage="development", soil="loam", area_m2=1000, pump_lpm=300,
                contacts=[Contact("f", "91000", "or"), Contact("s", "91111", "en")])
    base.update(kw)
    return Station(**base)


def raw_for(st, frac):
    cal = st.probes[0]
    return cal.raw_dry - frac * (cal.raw_dry - cal.raw_field_capacity)


def reading(st, frac, age_h=0.2, battery=4.0):
    r = raw_for(st, frac)
    return Reading(NOW - age_h * 3600, [r, r], 28.0, battery_v=battery)


# ---- agronomy -------------------------------------------------------------
def test_hargreaves_et0_is_plausible_for_odisha():
    may = et0_hargreaves(27, 38, 20.3, 135)
    december = et0_hargreaves(15, 28, 20.3, 350)
    assert 5.0 < may < 8.0
    assert 2.5 < december < 4.5
    assert may > december


def test_calibration_maps_endpoints():
    cal = ProbeCalibration(raw_dry=3000, raw_field_capacity=1300)
    assert cal.available_fraction(3000) == 0
    assert cal.available_fraction(1300) == 1
    assert cal.available_fraction(5000) == 0
    with pytest.raises(ValueError):
        ProbeCalibration(1000, 2000).available_fraction(1500)


def test_bad_station_config_rejected():
    with pytest.raises(ValueError):
        station(crop="rice-unknown")
    with pytest.raises(ValueError):
        station(stage="flowering")


# ---- advisor --------------------------------------------------------------
def test_wet_soil_is_ok():
    st = station()
    a = advise(st, reading(st, 0.9), [DRY, DRY], now=NOW)
    assert a.status == OK and a.pump_minutes == 0
    assert a.available_water_pct == pytest.approx(90, abs=1)


def test_dry_soil_needs_irrigation_with_correct_minutes():
    st = station()
    a = advise(st, reading(st, 0.5), [DRY, DRY], now=NOW)
    assert a.status == IRRIGATE_NOW
    crop, soil = CROPS["tomato"], SOILS["loam"]
    taw = 1000 * (soil.theta_fc - soil.theta_wp) * crop.root_depth("development")
    dr = 0.5 * taw
    expected = (dr / 0.60) * 1000 / 300  # furrow efficiency, 1000 m2, 300 L/min
    assert abs(a.pump_minutes - expected) <= 5
    assert not a.urgent


def test_advice_not_capped_by_auto_pump_limit():
    st = station(max_pump_minutes=30)
    a = advise(st, reading(st, 0.4), [DRY, DRY], now=NOW)
    assert a.pump_minutes > 30  # farmer is told the full requirement


def test_very_dry_is_urgent():
    st = station()
    a = advise(st, reading(st, 0.1), [DRY, DRY], now=NOW)
    assert a.status == IRRIGATE_NOW and a.urgent


def test_rain_forecast_skips_irrigation():
    st = station()
    a = advise(st, reading(st, 0.55), [WET, DRY], now=NOW)
    assert a.status == SKIP_RAIN and a.pump_minutes == 0


def test_light_or_unlikely_rain_does_not_skip():
    st = station()
    drizzle = DayForecast("d0", 3.0, 90, 4.5, 32, 25)
    unlikely = DayForecast("d0", 30.0, 10, 4.5, 32, 25)
    assert advise(st, reading(st, 0.5), [drizzle, DRY], now=NOW).status == IRRIGATE_NOW
    assert advise(st, reading(st, 0.5), [unlikely, DRY], now=NOW).status == IRRIGATE_NOW


def test_borderline_warns_irrigate_soon_unless_rain_tomorrow():
    st = station()
    a = advise(st, reading(st, 0.62), [DRY, DRY], now=NOW)
    assert a.status == IRRIGATE_SOON and a.pump_minutes > 0
    b = advise(st, reading(st, 0.62), [DRY, WET], now=NOW)
    assert b.status == OK and any("rain" in n for n in b.notes)


def test_stale_and_missing_data():
    st = station()
    assert advise(st, reading(st, 0.9, age_h=5), [DRY], now=NOW).status == SENSOR_STALE
    assert advise(st, None, [DRY], now=NOW).status == NO_DATA


def test_works_offline_without_forecast():
    st = station()
    a = advise(st, reading(st, 0.5), None, now=NOW, recent_temps=(25, 34))
    assert a.status == IRRIGATE_NOW
    assert not a.forecast_used and a.etc_mm_day > 0
    assert any("forecast unavailable" in n for n in a.notes)


def test_offline_et0_never_zero_with_short_history():
    st = station()
    a = advise(st, reading(st, 0.9), None, now=NOW, recent_temps=(31.2, 31.2))
    assert a.etc_mm_day > 2


def test_low_battery_flagged_in_message():
    st = station()
    a = advise(st, reading(st, 0.9, battery=3.3), [DRY], now=NOW)
    assert "battery low" in a.notes[0]
    assert "🔋" in render(a, st.name, "en")


# ---- messages -------------------------------------------------------------
@pytest.mark.parametrize("lang", ["or", "hi", "en"])
def test_every_status_renders_in_every_language(lang):
    st = station()
    cases = [reading(st, 0.9), reading(st, 0.5), reading(st, 0.1), reading(st, 0.9, age_h=6)]
    for r in cases:
        for fc in ([DRY, DRY], [WET, DRY]):
            text = render(advise(st, r, fc, now=NOW), st.name, lang)
            assert "{" not in text and st.name in text
    assert set(TEMPLATES[lang]) == set(TEMPLATES["en"])


def test_odia_message_uses_odia_script():
    st = station()
    text = render(advise(st, reading(st, 0.5), [DRY, DRY], now=NOW), st.name, "or")
    assert any("଀" <= ch <= "୿" for ch in text)


# ---- weather --------------------------------------------------------------
def test_open_meteo_parse_handles_nulls():
    payload = {"daily": {"time": ["2026-11-09", "2026-11-10"],
                         "precipitation_sum": [0.0, None],
                         "precipitation_probability_max": [10, 80],
                         "et0_fao_evapotranspiration": [3.9, 3.1],
                         "temperature_2m_max": [30.1, 28.0],
                         "temperature_2m_min": [19.5, 20.0]}}
    fc = parse(payload)
    assert len(fc) == 2 and fc[1].rain_mm == 0.0 and fc[1].rain_prob_pct == 80


# ---- service & storage ----------------------------------------------------
def make_service(tmp_path, forecast=(DRY, DRY), **kw):
    st = station(**kw)
    notifier = ConsoleNotifier()
    svc = Service({st.station_id: st}, Store(str(tmp_path / "t.db")), notifier,
                  forecast_fn=lambda lat, lon: list(forecast))
    return svc, st, notifier


def payload(st, frac, ts=NOW, seq=1):
    r = raw_for(st, frac)
    return {"station_id": st.station_id, "readings": [
        {"seq": seq, "ts": ts, "soil_raw": [r, r], "air_temp_c": 30, "battery_v": 4.0}]}


def test_duplicate_readings_ignored(tmp_path):
    svc, st, _ = make_service(tmp_path)
    assert svc.ingest(st, payload(st, 0.9), now=NOW)["stored"] == 1
    assert svc.ingest(st, payload(st, 0.9), now=NOW)["stored"] == 0


def test_alerts_sent_once_per_status_change(tmp_path):
    svc, st, notifier = make_service(tmp_path)
    svc.ingest(st, payload(st, 0.9, seq=1), now=NOW)
    assert notifier.sent == []                           # OK: no alert
    svc.ingest(st, payload(st, 0.5, ts=NOW + 900, seq=2), now=NOW + 900)
    assert len(notifier.sent) == 2                       # both contacts
    assert "ଜଳସେଚନ" in notifier.sent[0][1]               # Odia for the farmer
    svc.ingest(st, payload(st, 0.49, ts=NOW + 1800, seq=3), now=NOW + 1800)
    assert len(notifier.sent) == 2                       # same status: no repeat


def test_daily_advisory_always_sends(tmp_path):
    svc, st, notifier = make_service(tmp_path)
    svc.ingest(st, payload(st, 0.9), now=NOW)
    svc.daily_advisory(now=NOW + 60)
    assert len(notifier.sent) == 2


def test_pump_command_only_when_enabled_and_rate_limited(tmp_path):
    svc, st, _ = make_service(tmp_path)
    assert svc.ingest(st, payload(st, 0.5), now=NOW)["command"]["pump_minutes"] == 0
    (tmp_path / "b").mkdir()
    svc2, st2, _ = make_service(tmp_path / "b", auto_pump=True, max_pump_minutes=45)
    first = svc2.ingest(st2, payload(st2, 0.5), now=NOW)["command"]["pump_minutes"]
    assert first == 45                                   # capped for automatic control
    again = svc2.ingest(st2, payload(st2, 0.48, ts=NOW + 900, seq=2), now=NOW + 900)
    assert again["command"]["pump_minutes"] == 0         # 12 h minimum gap


def test_simulator_dries_by_etc_per_day():
    st = station()
    data = simulate(st, days=3, start_available=0.9, et0_mm=5.0)
    assert len(data) == 3 * 96
    first, last = data[0]["soil_raw"][0], data[-1]["soil_raw"][0]
    assert last > first  # drier soil -> higher raw value


# ---- HTTP end to end -------------------------------------------------------
@pytest.fixture
def running_server(tmp_path):
    svc, st, notifier = make_service(tmp_path)
    httpd = serve(svc, "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", st, notifier
    httpd.shutdown()


def test_http_ingest_auth_and_advice(running_server):
    base, st, _ = running_server
    body = payload(st, 0.5, ts=time.time())
    bad = requests.post(f"{base}/api/v1/readings", json=body, headers={"X-Device-Key": "nope"})
    assert bad.status_code == 401
    ok = requests.post(f"{base}/api/v1/readings", json=body, headers={"X-Device-Key": "secret"})
    assert ok.status_code == 200 and ok.json()["status"] == IRRIGATE_NOW
    adv = requests.get(f"{base}/api/v1/advice", params={"station_id": "s1"}).json()
    assert adv["status"] == IRRIGATE_NOW
    rows = requests.get(f"{base}/api/v1/readings", params={"station_id": "s1"}).json()
    assert len(rows) == 1
    page = requests.get(base + "/status")
    assert page.status_code == 200 and "Test Field" in page.text
    assert requests.get(base + "/").status_code == 200       # live dashboard
    assert requests.post(f"{base}/api/v1/readings", data="not json",
                         headers={"X-Device-Key": "secret"}).status_code == 400


def test_example_config_loads(tmp_path):
    from pathlib import Path
    stations = load_stations(Path(__file__).parent.parent / "stations.example.json")
    assert "phulnakhara-01" in stations
