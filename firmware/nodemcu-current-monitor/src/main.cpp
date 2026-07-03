#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>

#include "config.h"

// Number of ADC samples taken per RMS measurement. At ~50 samples/ms
// wall-clock on the ESP8266 this covers several mains cycles (50/60Hz).
static const int NUMBER_OF_SAMPLES = 1000;

static void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi connected, IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi connect failed, will retry next cycle");
  }
}

// Adapted from the classic EmonLib calcIrms approach: tracks a slow-moving
// DC offset so it works without knowing the exact bias-circuit midpoint,
// then RMS's the deviation from that offset across the sample window.
static double readRmsCurrent() {
  double offsetI = 512.0; // rough initial guess for a 10-bit ADC midpoint
  double sumSq = 0.0;

  for (int n = 0; n < NUMBER_OF_SAMPLES; n++) {
    int sample = analogRead(A0);
    offsetI += (sample - offsetI) / 1024.0;
    double filtered = sample - offsetI;
    sumSq += filtered * filtered;
  }

  double rms = sqrt(sumSq / NUMBER_OF_SAMPLES);
  return rms * CT_CALIBRATION;
}

static void postReading(double currentRmsA) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Skipping post, WiFi not connected");
    return;
  }

  double powerVaApprox = currentRmsA * ASSUMED_VOLTAGE_V;

  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["ts"] = (uint64_t)millis(); // Pi aggregator stamps authoritative receive time too
  doc["current_rms_a"] = currentRmsA;
  doc["power_va_approx"] = powerVaApprox;
  doc["assumed_voltage_v"] = ASSUMED_VOLTAGE_V;

  String body;
  serializeJson(doc, body);

  WiFiClient client;
  HTTPClient http;
  String url = String("http://") + PI_HOST + ":" + PI_PORT + "/ingest";

  if (!http.begin(client, url)) {
    Serial.println("HTTP begin failed");
    return;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Api-Key", PI_API_KEY);

  int status = http.POST(body);
  if (status > 0) {
    Serial.printf("POST %s -> %d\n", url.c_str(), status);
  } else {
    Serial.printf("POST failed: %s\n", http.errorToString(status).c_str());
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(200);
  connectWiFi();
}

void loop() {
  connectWiFi();

  double currentRmsA = readRmsCurrent();
  postReading(currentRmsA);

  delay(SAMPLE_INTERVAL_MS);
}
