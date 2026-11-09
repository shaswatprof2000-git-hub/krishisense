# KrishiSense 🌱

[![tests](https://github.com/shaswatprof2000-git-hub/krishisense/actions/workflows/tests.yml/badge.svg)](https://github.com/shaswatprof2000-git-hub/krishisense/actions/workflows/tests.yml)

**A solar soil and weather station that tells farmers when to irrigate, and for how long, on WhatsApp in Odia, Hindi or English.**

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
pytest -q                         # 26 tests
```

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
| GET | `/` | Status page |

The server uses only the Python standard library plus `requests`, so it runs on a Raspberry Pi.

## Design choices

- **Calibration lives on the server**, so the firmware sends raw values. Re-calibrating a probe never needs a re-flash.
- **Offline first:** the station keeps 24 h of readings in RTC memory and uploads them when the network returns. The advisor still works without the forecast.
- **Alerts don't spam:** a message goes out when the advice changes, repeats at most daily, and comes with a morning summary.
- **Pump safety:** automatic pump control is off by default. When enabled, each run is capped and there must be at least 12 hours between runs. The farmer is always told the full water requirement.

## Roadmap

- [ ] Field-test calibration and the advisor near Phulnakhara through one season. Compare water used vs. farmer's usual practice.
- [ ] Phase 2: pump relay + contactor, NPK sensor over RS485, LoRa for fields with no signal
- [ ] Paddy mode: alternate wetting and drying (AWD) using a water-level sensor in a field tube
- [ ] Voice messages in Odia for farmers who prefer audio
- [ ] Send sensor streams to Q-Sentinel for anomaly detection (pump failure, sensor drift)

## Notes

- Odia and Hindi messages should be reviewed by a native speaker from the area before going live.
- Crop and soil parameters come from FAO-56 tables. Tune root depth and calibration per field.
- Parts prices in the hardware guide are rough planning figures.

MIT licence · Shaswat Mohanty
