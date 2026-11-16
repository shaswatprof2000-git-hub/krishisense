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
- `docs/index.html`: public browser simulator (GitHub Pages). Core logic between the KS-CORE markers,
  tested by `docs/simulator.test.js`.

## Rules

- Calibration lives on the server; firmware sends raw ADC values.
- The farmer is always told the full pump time. `max_pump_minutes` caps only automatic relay runs.
- Alerts: each status at most once per 20 h; SOON is suppressed right after NOW; plus the morning advisory.
- Simulation mode never sends real WhatsApp messages; sim contacts are `SIMULATED-*`.
- Simulator results are illustrative, never presented as field results.
- Odia/Hindi text must be reviewed by a native speaker before going live.
- Any new crop or soil values must cite FAO-56 or another agronomy source.

## Roadmap

Wokwi virtual ESP32 in VS Code; field-test near Phulnakhara; phase 2 pump relay + NPK + LoRa; paddy AWD mode; Odia voice alerts.
