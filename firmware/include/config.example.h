// Copy this file to config.h (which is git-ignored) and fill in your values.
#pragma once

// ---- Identity ---------------------------------------------------------------
#define STATION_ID        "phulnakhara-01"
#define DEVICE_KEY        "change-me-long-random-string"   // must match server stations.json

// ---- Network ----------------------------------------------------------------
#define WIFI_SSID         "your-wifi-or-phone-hotspot"
#define WIFI_PASSWORD     "your-password"
// Full URL of the KrishiSense server ingest endpoint
#define SERVER_URL        "http://192.168.1.10:8080/api/v1/readings"

// ---- Timing -----------------------------------------------------------------
#define SLEEP_MINUTES     15        // reading interval
#define WIFI_TIMEOUT_MS   15000

// ---- Battery divider (e.g. 100k / 100k => factor 2.0) --------------------------
#define BATTERY_DIVIDER   2.0f

// ---- Pump control (phase 2) ---------------------------------------------------
// Keep 0 until the relay + contactor is installed by an electrician and tested.
#define ENABLE_PUMP_CONTROL   0
#define MAX_PUMP_MINUTES      60    // hard safety cap, whatever the server says
#define RELAY_ACTIVE_LOW      1     // most opto relay modules switch on LOW
