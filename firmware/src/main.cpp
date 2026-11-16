// KrishiSense field station: ESP32 + 2 capacitive soil probes + BME280 + solar battery.
//
// Every SLEEP_MINUTES the station wakes, powers the sensors, takes a reading and
// adds it to a buffer kept in RTC memory (it survives deep sleep). It then tries
// Wi-Fi: if the server is reachable, the whole buffer is uploaded in one POST, so
// readings taken while offline are not lost. The server replies with an optional
// pump command (phase 2). Raw ADC values are sent; calibration lives on the
// server, so re-calibrating never needs a re-flash.

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_BME280.h>
#include <ArduinoJson.h>
#ifdef USE_DHT22
#include <DHT.h>  // the Wokwi simulator has no BME280 part, so the virtual board uses a DHT22
#endif
#include <time.h>
#include "esp_sleep.h"

#ifdef KS_WOKWI
#include "config.wokwi.h"  // virtual board in Wokwi (see wokwi.toml / diagram.json)
#else
#include "config.h"
#endif

#ifndef SLEEP_SECONDS
#define SLEEP_SECONDS (SLEEP_MINUTES * 60UL)
#endif
#ifndef PUMP_SECONDS_PER_MINUTE
#define PUMP_SECONDS_PER_MINUTE 60UL  // the simulator can speed pump runs up
#endif

#define FW_VERSION "0.1.0"
#define BUFFER_SIZE 96            // 96 x 15 min = 24 h of offline storage
#define VALID_EPOCH 1704067200UL  // 2024-01-01: anything earlier means "clock not set"

struct Reading {
  uint32_t ts;          // unix time, 0 if the clock was never synced
  uint32_t seq;
  uint16_t soilTop;     // raw ADC (higher = drier for capacitive v1.2 probes)
  uint16_t soilDeep;
  float airTempC;
  float humidity;
  float pressureHpa;
  float batteryV;
};

RTC_DATA_ATTR Reading buffer[BUFFER_SIZE];
RTC_DATA_ATTR uint16_t bufCount = 0;
RTC_DATA_ATTR uint32_t seqCounter = 0;
RTC_DATA_ATTR uint32_t failedUploads = 0;

Adafruit_BME280 bme;
#ifdef USE_DHT22
DHT dht(PIN_DHT, DHT22);
#endif

static uint16_t readAdcAveraged(int pin, int samples = 16) {
  uint32_t sum = 0;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(pin);
    delay(5);
  }
  return sum / samples;
}

static float readBatteryVolts() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_BATTERY);
  return (mv / 8.0f) / 1000.0f * BATTERY_DIVIDER;
}

static void pumpWrite(bool on) {
  bool level = RELAY_ACTIVE_LOW ? !on : on;
  digitalWrite(PIN_PUMP_RELAY, level ? HIGH : LOW);
}

static Reading takeReading() {
  Reading r{};
  digitalWrite(PIN_SENSOR_POWER, HIGH);  // probes are powered only while measuring
  delay(500);                            // let the capacitive probes settle
  r.soilTop = readAdcAveraged(PIN_SOIL_TOP);
  r.soilDeep = readAdcAveraged(PIN_SOIL_DEEP);

#ifdef USE_DHT22
  dht.begin();
  delay(100);
  r.airTempC = dht.readTemperature();
  r.humidity = dht.readHumidity();
  r.pressureHpa = NAN;
#else
  if (bme.begin(0x76, &Wire) || bme.begin(0x77, &Wire)) {
    bme.setSampling(Adafruit_BME280::MODE_FORCED, Adafruit_BME280::SAMPLING_X1,
                    Adafruit_BME280::SAMPLING_X1, Adafruit_BME280::SAMPLING_X1,
                    Adafruit_BME280::FILTER_OFF);
    bme.takeForcedMeasurement();
    r.airTempC = bme.readTemperature();
    r.humidity = bme.readHumidity();
    r.pressureHpa = bme.readPressure() / 100.0f;
  } else {
    r.airTempC = r.humidity = r.pressureHpa = NAN;
    Serial.println("BME280 not found");
  }
#endif
  digitalWrite(PIN_SENSOR_POWER, LOW);

  r.batteryV = readBatteryVolts();
  time_t now = time(nullptr);
  r.ts = (now > (time_t)VALID_EPOCH) ? (uint32_t)now : 0;
  r.seq = seqCounter++;
  return r;
}

static void pushToBuffer(const Reading& r) {
  if (bufCount == BUFFER_SIZE) {  // full: drop the oldest reading
    memmove(&buffer[0], &buffer[1], sizeof(Reading) * (BUFFER_SIZE - 1));
    bufCount--;
  }
  buffer[bufCount++] = r;
}

static bool connectWifi() {
  WiFi.mode(WIFI_STA);
#ifdef WIFI_CHANNEL
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD, WIFI_CHANNEL);  // a fixed channel connects faster
#else
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
#endif
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) delay(250);
  if (WiFi.status() != WL_CONNECTED) return false;
  configTime(19800, 0, "pool.ntp.org", "time.google.com");  // IST = UTC+5:30
  struct tm t;
  getLocalTime(&t, 5000);
  return true;
}

static void addJsonNumber(JsonObject o, const char* key, float v) {
  if (isnan(v)) o[key] = nullptr; else o[key] = v;
}

// Returns pump minutes requested by the server (0 if none), or -1 on failure.
static int uploadBuffer() {
  JsonDocument doc;
  doc["station_id"] = STATION_ID;
  doc["fw"] = FW_VERSION;
  doc["failed_uploads"] = failedUploads;
  JsonArray arr = doc["readings"].to<JsonArray>();
  uint32_t now = (uint32_t)time(nullptr);
  for (uint16_t i = 0; i < bufCount; i++) {
    const Reading& r = buffer[i];
    JsonObject o = arr.add<JsonObject>();
    o["seq"] = r.seq;
    // Readings taken before the first time sync get a timestamp estimated from their age.
    uint32_t ts = r.ts;
    if (ts == 0 && now > VALID_EPOCH) ts = now - (bufCount - 1 - i) * SLEEP_SECONDS;
    o["ts"] = ts;
    JsonArray soil = o["soil_raw"].to<JsonArray>();
    soil.add(r.soilTop);
    soil.add(r.soilDeep);
    addJsonNumber(o, "air_temp_c", r.airTempC);
    addJsonNumber(o, "humidity", r.humidity);
    addJsonNumber(o, "pressure_hpa", r.pressureHpa);
    addJsonNumber(o, "battery_v", r.batteryV);
  }
  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  http.setTimeout(10000);
  int code = http.POST(body);
  int pumpMinutes = -1;
  if (code == 200) {
    JsonDocument resp;
    if (!deserializeJson(resp, http.getString())) {
      pumpMinutes = resp["command"]["pump_minutes"] | 0;
    } else {
      pumpMinutes = 0;
    }
  } else {
    Serial.printf("Upload failed: HTTP %d\n", code);
  }
  http.end();
  return pumpMinutes;
}

static void runPump(int minutes) {
#if ENABLE_PUMP_CONTROL
  if (minutes <= 0) return;
  if (minutes > MAX_PUMP_MINUTES) minutes = MAX_PUMP_MINUTES;
  Serial.printf("Pump ON for %d min\n", minutes);
  WiFi.disconnect(true);  // save power while waiting
  WiFi.mode(WIFI_OFF);
  pumpWrite(true);
  delay((uint32_t)minutes * PUMP_SECONDS_PER_MINUTE * 1000UL);
  pumpWrite(false);
  Serial.println("Pump OFF");
#else
  if (minutes > 0) Serial.printf("Server asked for %d pump minutes (pump control disabled)\n", minutes);
#endif
}

void setup() {
  pinMode(PIN_PUMP_RELAY, OUTPUT);
  pumpWrite(false);  // always start with the pump OFF
  pinMode(PIN_SENSOR_POWER, OUTPUT);
  digitalWrite(PIN_SENSOR_POWER, LOW);
  Serial.begin(115200);
  delay(200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  Reading r = takeReading();
  pushToBuffer(r);
  Serial.printf("seq=%lu soil=%u/%u T=%.1fC RH=%.0f%% batt=%.2fV buffered=%u\n",
                (unsigned long)r.seq, r.soilTop, r.soilDeep, r.airTempC, r.humidity,
                r.batteryV, bufCount);

  if (connectWifi()) {
    int pump = uploadBuffer();
    if (pump >= 0) {
      bufCount = 0;
      failedUploads = 0;
      runPump(pump);
    } else {
      failedUploads++;
    }
  } else {
    failedUploads++;
    Serial.println("Wi-Fi unavailable, reading kept in buffer");
  }

  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  esp_sleep_enable_timer_wakeup((uint64_t)SLEEP_SECONDS * 1000000ULL);
  esp_deep_sleep_start();
}

void loop() {}  // never reached: the station deep-sleeps between readings
