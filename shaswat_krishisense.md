# KrishiSense: project notes

Solar soil and weather station (ESP32) plus an irrigation advisor that sends WhatsApp alerts in
Odia, Hindi or English.

## Commands

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                          # 30 tests
node ../docs/simulator.test.js     # browser simulator logic
python -m krishisense demo         # 12 simulated days, no hardware needed
python -m krishisense sim          # virtual stations + live dashboard on :8080
python -m krishisense sim --fast   # season report only
python -m krishisense serve        # API + status page on :8080 (needs stations.json)
python -m krishisense advise --send
cd ../firmware && pio run -e esp32dev -t upload
pio run -e wokwi                   # virtual board; then F1 -> "Wokwi: Start Simulator" (diagram.json)
python -m krishisense --config stations.wokwi.json --db wokwi.db serve   # server the Wokwi board uploads to
```

## Layout

- `firmware/`: PlatformIO ESP32 code. Sends raw readings and buffers 24 h offline. Pump relay is off by default.
- `hardware/README.md`: parts list, wiring, power budget, calibration, pump safety.
- `server/krishisense/`: `agronomy.py` (FAO-56 crop/soil tables, Hargreaves ET0),
  `advisor.py` (water-balance decision), `weather.py` (Open-Meteo), `messages.py` (or/hi/en),
  `notify.py` (WhatsApp Cloud API, console dry run), `store.py` (SQLite), `server.py` (stdlib HTTP),
  `service.py` (alerts, pump commands), `simulate.py`, `cli.py`,
  `simworld.py` (seeded weather + imperfect forecasts, simulated clock),
  `virtual_station.py` (virtual ESP32 stations, field water model, offline buffer, farmer behaviour),
  `dashboard.html` (live dashboard served at `/`).
- Wokwi: `wokwi.toml` + `diagram.json` (repo root), `firmware/include/config.wokwi.h` (env `wokwi`:
  DHT22 instead of BME280, 15 s interval, host.wokwi.internal:8080, pump enabled at 1 s per minute),
  `server/stations.wokwi.json` (station `wokwi-01`, key `wokwi-demo-key`).
- `.vscode/`: recommended extensions + tasks (build Wokwi firmware, server for Wokwi, simulation, tests).
- `docs/farm3d.html`: three.js 3D view (CDN, pinned 0.170.0) driven by `farm-engine.js`.
- `docs/` (GitHub Pages site, opens from the link with no install):
  `index.html` live farm dashboard driven by `farm-engine.js` (JS port of virtual stations + advisor +
  alert rules, answering the same /api/v1 paths as the server); `season.html` KrishiSense vs fixed-schedule
  comparison (core between the KS-CORE markers). Both tested by `docs/simulator.test.js`.
- Keep `farm-engine.js` in step with `advisor.py`, `messages.py` and `service.py` when those change.

## Rules

- Calibration lives on the server; firmware sends raw ADC values.
- The farmer is always told the full pump time. `max_pump_minutes` caps only automatic relay runs.
- Alerts: each status at most once per 20 h; SOON is suppressed right after NOW; plus the morning advisory.
- Simulation mode never sends real WhatsApp messages; sim contacts are `SIMULATED-*`.
- Simulator results are illustrative, never presented as field results.
- Odia/Hindi text must be reviewed by a native speaker before going live.
- Any new crop or soil values must cite FAO-56 or another agronomy source.

## Roadmap

field-test near Phulnakhara; phase 2 pump relay + NPK + LoRa; paddy AWD mode; Odia voice alerts.
