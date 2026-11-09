# KrishiSense: project notes

Solar soil and weather station (ESP32) plus an irrigation advisor that sends WhatsApp alerts in
Odia, Hindi or English.

## Commands

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                          # 26 tests
python -m krishisense demo         # 12 simulated days, no hardware needed
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
  `service.py` (alerts, pump commands), `simulate.py`, `cli.py`.

## Rules

- Calibration lives on the server; firmware sends raw ADC values.
- The farmer is always told the full pump time. `max_pump_minutes` caps only automatic relay runs.
- Alerts: on status change, at most daily repeats, plus the morning advisory.
- Odia/Hindi text must be reviewed by a native speaker before going live.
- Any new crop or soil values must cite FAO-56 or another agronomy source.

## Roadmap

Field-test near Phulnakhara; phase 2 pump relay + NPK + LoRa; paddy AWD mode; Odia voice alerts.
