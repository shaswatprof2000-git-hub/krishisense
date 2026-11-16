# KrishiSense 🌱

[![tests](https://github.com/shaswatprof2000-git-hub/krishisense/actions/workflows/tests.yml/badge.svg)](https://github.com/shaswatprof2000-git-hub/krishisense/actions/workflows/tests.yml)

**A solar soil and weather station that tells farmers when to irrigate, and for how long, on WhatsApp in Odia, Hindi or English.**

▶ **[Open KrishiSense](https://shaswatprof2000-git-hub.github.io/krishisense/)**: one website with everything, running in your browser with nothing to install. Pick a view from the sidebar; they all share one simulated farm and one clock:

| View | What you can do |
|---|---|
| Overview | See the three farms right now, the latest WhatsApp message, and how the pieces connect |
| Live dashboard | Watch every station's soil water, pump runs and WhatsApp alerts |
| 3D twin | Fly around the farms, click a field to see its root zone, probes and advice; drag through the season |
| Season comparison | Compare KrishiSense with watering on a fixed schedule, for any crop and soil |
| Hardware lab | Wiring of the virtual ESP32, how to run it in VS Code, and the real station's parts |

Farmers usually irrigate by habit or by looking at the soil surface. That often means too much water, too
much diesel or electricity, and stressed crops when they guess wrong. KrishiSense measures soil moisture at
two depths, checks the rain forecast, and sends one clear message each morning:

> 🌱 Phulnakhara Plot 1: ଜଳସେଚନ ଦରକାର। ଆଜି ପମ୍ପ 160 ମିନିଟ୍ ଚଲାନ୍ତୁ। ମାଟି ଆର୍ଦ୍ରତା: 55%
>
> 🌧️ Don't irrigate. About 30 mm of rain is likely in the next 24 hours (85%).

## How it works

```
 Field station (ESP32, solar)                 Server (Raspberry Pi / laptop / VPS)
 ┌───────────────────────────┐   Wi-Fi/4G   ┌──────────────────────────────────────┐
 │ soil probes 15 cm + 30 cm │ ───────────▶ │ store readings (SQLite)              │
 │ BME280 temp/humidity      │  every 15min │ + Open-Meteo rain & ET0 forecast     │
 │ battery voltage           │              │ + FAO-56 root-zone water balance     │
 │ 24 h offline buffer       │ ◀─────────── │ = advice -> WhatsApp (or / hi / en)  │
 │ pump relay (phase 2)      │ pump command │   status page at  http://server:8080 │
 └───────────────────────────┘              └──────────────────────────────────────┘
```

**The decision** follows FAO Irrigation Paper 56, the standard method agronomists use:

1. Probe readings are converted into how much plant-available water is left in the root zone, using a
   simple two-point calibration done in the actual field.
2. The crop starts to stress once depletion passes the crop's readily available water
   (`RAW = p × TAW`, e.g. 40% for tomato).
3. When that happens, the advisor checks the forecast. If likely rain covers most of the need, it says
   **skip**. Otherwise it works out the water needed to refill the root zone and converts it into
   **pump minutes**, using field area, pump flow and irrigation-method efficiency.
4. If today's crop water use (`ETc = Kc × ET0`) will cross the line within a day, it warns to
   **irrigate tomorrow morning**, unless rain is due tomorrow.
5. With no internet, it still works. It estimates water use from the station's own temperatures
   (Hargreaves method) and says the rain forecast wasn't considered.

Crops included: tomato, brinjal, chilli, maize, groundnut, cabbage, potato, watermelon. Soils: sandy to clay.

## Try it in 1 minute (no hardware)

```bash
cd server
pip install -e ".[dev]"
python -m krishisense demo        # 12 simulated days: OK -> irrigate soon -> irrigate now -> skip for rain
pytest -q                         # 31 tests
```

## Simulation: the whole system without hardware

Build and test in three stages, so nothing is bought until the software is proven:

| Stage | What runs | Command / tool |
|---|---|---|
| **1. Software simulation** | Virtual field stations + the real server + live dashboard | `python -m krishisense sim` |
| **2. Virtual hardware** | The real ESP32 firmware on a simulated board, talking to the real server | Wokwi in VS Code, see below |
| **3. Real hardware** | Solar ESP32 station in the field | see [`hardware/`](hardware/README.md) |

```bash
cd server
python -m krishisense sim                       # 30 simulated days, 1 hour per second; opens the dashboard
python -m krishisense sim --days 14 --speed 7200 --rain 0.25
python -m krishisense sim --fast                # no server or browser: just the season report
```

`sim` starts three virtual stations that behave like the real firmware. Each one sends the same JSON every
15 minutes over HTTP, buffers readings when its network drops and uploads them later, and runs a battery
model. Behind them is a simulated field: crop water use through the day, rain from a seeded weather
scenario, and forecasts that are sometimes wrong, as real ones are.

- **Tomato, loam, furrow:** the farmer reads the WhatsApp advice at 07:00 and follows it 9 times in 10.
- **Groundnut, sandy loam, drip:** automatic pump control through the relay command.
- **Chilli, silty clay loam, sprinkler:** the network is down for 12 hours on day 4, which tests the offline
  buffer and the "no sensor data" alert.

The server runs unchanged, in simulation mode: its clock follows the readings and it uses the scenario's
forecast instead of Open-Meteo. The dashboard at `http://localhost:8080` shows each station's soil water,
refill point, pump runs and the WhatsApp messages it would have sent. Nothing is sent to real phones.

**In the browser, with nothing to install:** [the website](https://shaswatprof2000-git-hub.github.io/krishisense/)
(`docs/`) runs the same three stations, advisor and alert rules as JavaScript (`docs/farm-engine.js`). The hub page
(`docs/index.html`) owns one shared season, and the dashboard (`live.html`) and 3D twin (`farm3d.html`) embedded in it
read that season, so pausing or jumping to a day moves every view. Each page also works on its own. The
[season comparison](https://shaswatprof2000-git-hub.github.io/krishisense/season.html) (`docs/season.html`) is a
simplified model that compares a KrishiSense farmer with a fixed watering schedule; its KrishiSense farmer
waters on the day the advice says so. Results from all the simulators are illustrative, not field results.

## Virtual hardware: the real firmware on a simulated ESP32 (Wokwi)

[Wokwi](https://wokwi.com) simulates the ESP32 inside VS Code. The board in [`diagram.json`](diagram.json) is wired
like the field station:

| Real station | Virtual board | Pin |
|---|---|---|
| Soil probe 15 cm / 30 cm | two slide potentiometers (slide up = drier) | GPIO34 / GPIO35 |
| BME280 temperature + humidity | DHT22 (Wokwi has no BME280 part) | GPIO27 |
| Battery divider | rotary potentiometer | GPIO33 |
| Sensor power switch | green LED | GPIO25 |
| Pump relay + contactor | relay module + blue "pump" LED | GPIO26 |

The `wokwi` build ([`firmware/include/config.wokwi.h`](firmware/include/config.wokwi.h)) joins Wokwi's virtual Wi-Fi,
takes a reading every 15 seconds instead of 15 minutes, and uploads to the KrishiSense server on your own computer
(`host.wokwi.internal:8080`) through the gateway built into Wokwi for VS Code. Pump control is switched on in the
simulator, and each pump minute lasts one second.

1. Open the repo in VS Code and install the recommended extensions it offers: Wokwi Simulator, PlatformIO, Python.
2. Get a Wokwi licence: F1 → **Wokwi: Request a new License** (free for open-source projects).
3. Build: **Terminal → Run Task → KrishiSense: build Wokwi firmware** (or `cd firmware && pio run -e wokwi`).
4. Start the server: **Run Task → KrishiSense: server for Wokwi** (or
   `cd server && python -m krishisense --config stations.wokwi.json --db wokwi.db serve`).
5. Open `diagram.json`, then F1 → **Wokwi: Start Simulator**. Keep the simulator tab visible.
6. Open http://localhost:8080. Slide the soil probes up to dry the soil and watch the advice change, the
   WhatsApp messages appear in the feed, and the relay switch the pump LED on.

The same firmware, unchanged except for its config file, runs on the real board.

## Run it for real

**1. Build the station.** See [`hardware/README.md`](hardware/README.md) for the parts list (about
₹2,000–3,500), wiring, power budget, calibration and pump safety.

**2. Flash the firmware** ([PlatformIO](https://platformio.org)):

```bash
cd firmware
cp include/config.example.h include/config.h     # Wi-Fi, server URL, station ID, device key
pio run -e esp32dev -t upload && pio device monitor
```

**3. Start the server:**

```bash
cd server
cp stations.example.json stations.json           # field location, crop, soil, area, pump flow, contacts
python -m krishisense serve --port 8080          # dashboard: http://<server-ip>:8080
```

**4. Schedule alerts** with `crontab -e`:

```
30 6 * * *  cd /path/to/server && python -m krishisense advise --send   # morning advisory
0  * * * *  cd /path/to/server && python -m krishisense check           # silent-station check
```

**5. WhatsApp:** set `WHATSAPP_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` (Meta WhatsApp Cloud API).
Without them, messages print to the console (dry run). WhatsApp only allows free-form messages within
24 hours of the farmer's last reply. For scheduled alerts, register an approved template message, or ask
farmers to reply "OK" each morning. See `server/krishisense/notify.py`.

## API

| Method | Path | Use |
|---|---|---|
| POST | `/api/v1/readings` | Device upload (header `X-Device-Key`). Returns `{"command": {"pump_minutes": n}}` |
| GET | `/api/v1/advice?station_id=…` | Current advice as JSON |
| GET | `/api/v1/readings?station_id=…&limit=100` | Recent readings |
| GET | `/api/v1/stations` | All stations with current advice (used by the dashboard) |
| GET | `/api/v1/history?station_id=…&days=7` | Soil water % over time |
| GET | `/api/v1/pump?station_id=…` / `/api/v1/alerts` | Pump runs and alert log |
| GET | `/` | Live dashboard |
| GET | `/status` | Plain status table |

The server uses only the Python standard library plus `requests`, so it runs on a Raspberry Pi.

## Design choices

- **Calibration lives on the server**, so the firmware sends raw values. Re-calibrating a probe never needs a re-flash.
- **Offline first:** the station keeps 24 h of readings in RTC memory and uploads them when the network returns. The advisor still works without the forecast.
- **Alerts don't spam:** each kind of alert goes out at most once in 20 hours, an "irrigate soon" is dropped if "irrigate now" was just sent, and there is one morning summary.
- **Pump safety:** automatic pump control is off by default. When enabled, each run is capped and there must be at least 12 hours between runs. The farmer is always told the full water requirement.

## Roadmap

- [ ] Field-test calibration and the advisor near Phulnakhara through one season. Compare water used vs. farmer's usual practice.
- [x] Software simulation: virtual stations, simulation mode, live dashboard, browser simulator
- [x] Wokwi virtual ESP32 in VS Code, talking to the local server
- [x] 3D farm view in the browser
- [ ] Phase 2: pump relay + contactor, NPK sensor over RS485, LoRa for fields with no signal
- [ ] Paddy mode: alternate wetting and drying (AWD) using a water-level sensor in a field tube
- [ ] Voice messages in Odia for farmers who prefer audio
- [ ] Send sensor streams to Q-Sentinel for anomaly detection (pump failure, sensor drift)

## Notes

- Odia and Hindi messages should be reviewed by a native speaker from the area before going live.
- Crop and soil parameters come from FAO-56 tables. Tune root depth and calibration per field.
- Parts prices in the hardware guide are rough planning figures.

MIT licence · Shaswat Mohanty
