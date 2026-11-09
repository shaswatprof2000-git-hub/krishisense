# KrishiSense hardware (v1 field station)

## Bill of materials

Prices are rough Indian retail ranges for planning only. Check current prices before ordering.

| # | Part | Qty | Notes | Approx. ₹ |
|---|---|---|---|---|
| 1 | ESP32 board: **LOLIN D32 / FireBeetle ESP32** (low deep-sleep current, built-in Li-ion charger) | 1 | A classic ESP32 DevKit works for bench testing, but its USB chip draws ~10 mA in deep sleep, which drains the battery | 450–900 |
| 2 | Capacitive soil moisture sensor v1.2 or v2.0 | 2 | One at ~15 cm, one at ~30 cm depth. Seal the electronics end with epoxy or heat-shrink | 80–150 each |
| 3 | BME280 module (temperature, humidity, pressure; I²C) | 1 | Not BMP280, which has no humidity | 250–450 |
| 4 | 18650 Li-ion cell (2,600–3,400 mAh) + holder | 1–2 | Buy from a reputable seller | 200–400 each |
| 5 | Solar panel, 6 V, 2–5 W | 1 | Tilt it south at roughly 20° | 300–700 |
| 6 | Solar charge controller: CN3791 MPPT module (or a TP4056 with protection) | 1 | Not needed if the board charges directly from a 5–6 V panel; check its specs | 150–300 |
| 7 | 100 kΩ + 100 kΩ resistors (battery voltage divider) | 2 | | 5 |
| 8 | IP65 junction box + cable glands | 1 | Mount 1–1.5 m high on a pole, out of floodwater | 250–500 |
| 9 | 3-core shielded cable, 2–3 m | 1 | For the soil probes | 100 |
| 10 | GI pipe or bamboo pole, mounting clamps | 1 | | 150–300 |
| **Phase 2** | | | | |
| 11 | 1-channel opto-isolated 5 V relay module | 1 | It switches only a **contactor coil**, never the motor directly | 80–150 |
| 12 | Contactor / motor starter rated for the pump | 1 | Installed by a licensed electrician | varies |
| 13 | RS485 soil NPK sensor + MAX485 module | 1 | Optional nutrient readings | 2,500–5,000 |
| 14 | LoRa SX1276 (865 MHz India band) modules | 2 | For fields without a mobile signal | 500–900 each |

Phase 1 total: roughly ₹2,000–3,500 per station.

## Wiring (esp32dev pin numbers; see `platformio.ini` for ESP32-S3)

```
                        ESP32
 Soil probe TOP  AOUT --> GPIO34 (ADC1)
 Soil probe DEEP AOUT --> GPIO35 (ADC1)
 Both probes VCC      --> GPIO25   (sensor power: on only while measuring)
 Both probes GND      --> GND

 BME280 VIN --> 3V3     SDA --> GPIO21    SCL --> GPIO22    GND --> GND

 Battery + --[100k]--+--[100k]-- GND
                     +--> GPIO33        (reads half the battery voltage)

 Relay IN (phase 2) --> GPIO26   Relay VCC --> 5V/VIN   GND --> GND
```

Use only **ADC1** pins (GPIO32–39 on the classic ESP32). ADC2 doesn't work while Wi-Fi is on.

## Power budget (LOLIN D32-class board)

| State | Current | Time per 15 min | Charge |
|---|---|---|---|
| Deep sleep | ~0.1 mA | ~14.5 min | 0.024 mAh |
| Measure + Wi-Fi upload | ~120 mA | ~8 s | 0.27 mAh |
| **Per day** | | | **≈ 28 mAh** |

A 3,000 mAh cell runs for about **3 months with no sun at all**, so a 2 W panel easily covers the monsoon.

## Calibration (do this in the actual field soil)

Capacitive probes give a raw number, and *higher means drier*. The server converts it to
"plant-available water %" using two field readings per probe:

1. **Field capacity:** irrigate deeply, wait about 24 hours for drainage, then note the raw reading as `raw_field_capacity`.
2. **Dry point:** note the raw reading when the crop first shows midday wilting (or from a dry soil sample from the same field) as `raw_dry`.
3. Put both numbers in `server/stations.json` for that probe.

Until you calibrate, the defaults (air ≈ 3,000, water ≈ 1,300) give rough results only.

## Installation tips

- Insert the probes vertically into a hole you've made, then press soil back firmly. Air gaps cause false "dry" readings.
- Put the station in a spot that represents the field, not the wettest or driest corner.
- Coat the top of each probe's PCB with epoxy or nail polish. Uncoated probes corrode within one season.
- Keep the junction box above flood level. Most field failures come from water getting into the electronics.

## ⚠️ Pump safety

Pumps run on 230 V or 415 V. The ESP32 relay must only switch the low-voltage **coil of a
properly rated contactor** or starter, fitted by a licensed electrician with an MCB and earthing.
Keep `ENABLE_PUMP_CONTROL 0` until that installation is done and tested. The firmware caps any
single run at `MAX_PUMP_MINUTES` and always starts with the pump off.
