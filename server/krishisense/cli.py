"""Command line:  python -m krishisense <command> [--config stations.json] [--db krishisense.db]

  serve   [--port 8080]       run the HTTP API + status page
  advise  [--send]            print today's advice (and send WhatsApp with --send)
  check                       hourly check for silent stations (for cron)
  demo                        simulate a week of sensor data and show the advice + alerts
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
    d = sub.add_parser("demo")
    d.add_argument("--days", type=int, default=12)
    args = ap.parse_args(argv)

    if args.cmd == "demo":
        return demo(args)

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
