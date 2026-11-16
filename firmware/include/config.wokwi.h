// Settings for the virtual board in the Wokwi simulator (pio run -e wokwi).
// Safe to commit: it only talks to a KrishiSense server on your own computer.
#pragma once

#define STATION_ID        "wokwi-01"
#define DEVICE_KEY        "wokwi-demo-key"      // matches server/stations.wokwi.json

// Wokwi's simulated Wi-Fi. host.wokwi.internal is your own computer (VS Code's built-in gateway).
#define WIFI_SSID         "Wokwi-GUEST"
#define WIFI_PASSWORD     ""
#define WIFI_CHANNEL      6
#define SERVER_URL        "http://host.wokwi.internal:8080/api/v1/readings"

// Faster than the field so you can watch it work: a reading every 15 s instead of 15 min.
#define SLEEP_MINUTES     15
#define SLEEP_SECONDS     15
#define WIFI_TIMEOUT_MS   15000

// 0: stay awake between readings (loop + delay, Wi-Fi stays up). The simulator reset
//    with TG1WDT_SYS_RESET on the way into deep sleep, right after a successful upload.
// 1: use the real deep-sleep path, to test the simulator's deep sleep support.
#define WOKWI_DEEP_SLEEP  0

// The battery is a potentiometer on GPIO33 in the simulator.
#define BATTERY_DIVIDER   1.3f

// Pump: the relay and the blue "pump" LED in the diagram. Simulated, so it is enabled,
// and each pump minute the server asks for lasts 1 second.
#define ENABLE_PUMP_CONTROL     1
#define MAX_PUMP_MINUTES        60
#define RELAY_ACTIVE_LOW        0
#define PUMP_SECONDS_PER_MINUTE 1UL
