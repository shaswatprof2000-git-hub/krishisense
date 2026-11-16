"""Command line:  python -m krishisense <command> [--config stations.json] [--db krishisense.db]

  serve   [--port 8080]       run the HTTP API + status page
  advise  [--send]            print today's advice (and send WhatsApp with --send)
  check                       hourly check for silent stations (for cron)
  demo                        simulate a week of sensor data and show the advice + alerts
  sim     [--days 30] [--speed 3600] [--port 8080] [--fast]
                              full software simulation: server in simulation mode + 3 virtual
                              field stations + live dashboard at http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse

from .config import load_stations
from .notify import ConsoleNotifier, notifier_from_env
from .service import Service
from .store import Store


def main(argv=None):
    ap = argparse.ArgumentParser(prog="krishisense", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="stations.json")
    ap.add_argument("--db", default="krishisense.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    a = sub.add_parser("advise")
    a.add_argument("--send", action="store_true")
    sub.add_parser("check")
    sm = sub.add_parser("sim")
    sm.add_argument("--days", type=float, default=30)
    sm.add_argument("--speed", type=float, default=3600, help="simulated seconds per real second")
    sm.add_argument("--port", type=int, default=8080)
    sm.add_argument("--seed", type=int, default=7)
    sm.add_argument("--rain", type=float, default=0.15, help="share of rainy days")
    sm.add_argument("--fast", action="store_true", help="no waiting: run to the end, print the report")
    sm.add_argument("--keep-open", action="store_true", help="keep the dashboard running after the end")
    d = sub.add_parser("demo")
    d.add_argument("--days", type=int, default=12)
    args = ap.parse_args(argv)

    if args.cmd == "demo":
        return demo(args)
    if args.cmd == "sim":
        return sim(args)

    stations = load_stations(args.config)
    store = Store(args.db)
    if args.cmd == "serve":
        from .server import serve
        svc = Service(stations, store, notifier_from_env())
        httpd = serve(svc, args.host, args.port)
        print(f"KrishiSense listening on http://{args.host}:{args.port}  ({len(stations)} station(s))")
        httpd.serve_forever()
    elif args.cmd == "advise":
        svc = Service(stations, store, notifier_from_env() if args.send else ConsoleNotifier())
        if args.send:
            svc.daily_advisory()
        else:
            for st in stations.values():
                adv = svc.evaluate(st)
                print(st.name, adv.to_dict())
    elif args.cmd == "check":
        Service(stations, store, notifier_from_env()).check_all()


def sim(args):
    """Software simulation of the whole system, no hardware needed."""
    import os
    import tempfile
    import threading
    import time as _time

    from .notify import ConsoleNotifier
    from .server import serve
    from .simworld import WeatherScenario
    from .virtual_station import HttpTransport, InProcessTransport, demo_fields, demo_stations, run

    class SilentNotifier(ConsoleNotifier):
        def send(self, to, text):  # alerts are logged and shown on the dashboard instead
            self.sent.append((to, text))
            return True

    scenario = WeatherScenario(seed=args.seed, rain_chance=args.rain)
    stations = demo_stations()
    db = os.path.join(tempfile.gettempdir(), "krishisense_sim.db")
    if os.path.exists(db):
        os.remove(db)
    svc = Service({s.station_id: s for s in stations}, Store(db), SilentNotifier(), scenario=scenario)
    fields = demo_fields(scenario, stations)
    last_check = [0.0]

    def on_tick(ts, _fields):
        if ts - last_check[0] >= 3600:  # hourly silent-station check, like the cron job
            svc.check_all(ts)
            last_check[0] = ts

    if args.fast:
        t0 = _time.time()
        report = run(fields, InProcessTransport(svc), days=args.days, on_tick=on_tick)
        print(f"Simulated {args.days:g} days for {len(fields)} stations in {_time.time() - t0:.0f} s")
    else:
        httpd = serve(svc, "127.0.0.1", args.port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{args.port}"
        print(f"Dashboard: {url}   (simulating {args.days:g} days at {args.speed:g}x; Ctrl+C to stop)")
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
        try:
            report = run(fields, HttpTransport(url), days=args.days, speed=args.speed, on_tick=on_tick)
        except KeyboardInterrupt:
            report = [f.summary() for f in fields]
    print()
    for r in report:
        print(f"{r['station']}\n   {r['crop']}, {r['soil']}, {r['mode']}\n"
              f"   water used {r['water_m3']} m3 in {r['pump_runs']} pump runs | rain {r['rain_mm']} mm | "
              f"crop stress {r['stress_hours']} h (severe {r['severe_stress_hours']} h) | "
              f"max readings buffered offline {r['max_buffered_readings']}")
    alerts = svc.store.alerts(limit=10000)
    print(f"\nWhatsApp alerts logged: {len(alerts)} (both languages), database: {db}")
    if not args.fast and args.keep_open:
        print("Dashboard still running; Ctrl+C to quit.")
        try:
            while True:
                _time.sleep(3600)
        except KeyboardInterrupt:
            pass


def demo(args):
    """Self-contained demo: no config, no hardware, no network.

    A field is simulated day by day. Each morning the advisor reads the probes and
    the forecast; when it says IRRIGATE_NOW the farmer runs the pump as advised.
    Rain is forecast for (and falls on) day 11.
    """
    from .advisor import IRRIGATE_NOW, Reading, advise
    from .agronomy import CROPS, IRRIGATION_EFFICIENCY, SOILS
    from .config import Station
    from .messages import render
    from .weather import DayForecast

    st = Station("demo-01", "Phulnakhara Demo", "k", 20.39, 85.86, crop="tomato",
                 stage="development", soil="loam", area_m2=1000, pump_lpm=300)
    crop, soil = CROPS[st.crop], SOILS[st.soil]
    taw = 1000 * (soil.theta_fc - soil.theta_wp) * crop.root_depth(st.stage)
    avail = 0.80 * taw
    dry_day = DayForecast("", 0.0, 5, 4.8, 33, 25)
    rain_day = DayForecast("", 30.0, 85, 3.0, 29, 24)
    rain_on = 11
    t0 = 1_730_000_000
    print(f"Tomato, development stage, loam, 1000 m2, 300 L/min pump, furrow. TAW = {taw:.0f} mm\n")
    for day in range(args.days):
        cal = st.probes[0]
        frac = avail / taw
        raw = cal.raw_dry - frac * (cal.raw_dry - cal.raw_field_capacity)
        fc = [rain_day if day == rain_on else dry_day, rain_day if day + 1 == rain_on else dry_day]
        ts = t0 + day * 86400
        adv = advise(st, Reading(ts, [raw, raw - 30], 26.0, battery_v=4.05), fc, now=ts + 60)
        print(f"Day {day}: soil water {adv.available_water_pct:.0f}%  ->  {adv.status} {adv.pump_minutes or ''}")
        print(f"   ଓଡ଼ିଆ : {render(adv, st.name, 'or')}")
        print(f"   EN   : {render(adv, st.name, 'en')}")
        if adv.notes:
            print(f"   note : {'; '.join(adv.notes)}")
        if adv.status == IRRIGATE_NOW:  # farmer follows the advice
            avail += adv.pump_minutes * st.pump_lpm * IRRIGATION_EFFICIENCY[st.irrigation_method] / st.area_m2
        avail -= crop.kc(st.stage) * (rain_day.et0_mm if day == rain_on else dry_day.et0_mm)
        if day == rain_on:
            avail += 0.8 * rain_day.rain_mm
        avail = max(0.0, min(avail, taw))


if __name__ == "__main__":
    main()
