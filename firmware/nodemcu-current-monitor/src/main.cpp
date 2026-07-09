#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>
#include <SoftwareSerial.h>
#include <PZEM004Tv30.h>

#include "config.h"

// PZEM-004T talks Modbus-RTU over TTL UART at a fixed 9600 baud. NodeMCU's
// one hardware UART is tied up with USB/Serial for logging, so the PZEM
// gets a SoftwareSerial pair instead. Cross-wire: PZEM TX -> NodeMCU RX pin,
// PZEM RX -> NodeMCU TX pin (through a voltage divider/level shifter if your
// module is 5V logic).
static const int PZEM_RX_PIN = D2;
static const int PZEM_TX_PIN = D1;

SoftwareSerial pzemSerial(PZEM_RX_PIN, PZEM_TX_PIN);
PZEM004Tv30 pzem(pzemSerial);

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

struct Reading {
  float voltageV;
  float currentA;
  float powerW;
  float energyKwh;
  float frequencyHz;
  float powerFactor;
  bool valid;
};

// The PZEM library returns NAN for any field it couldn't read (e.g. the
// module isn't wired up yet, or a Modbus frame got garbled) rather than
// throwing, so a reading is only usable if the core fields all came back.
static Reading readPzem() {
  Reading r;
  r.voltageV = pzem.voltage();
  r.currentA = pzem.current();
  r.powerW = pzem.power();
  r.energyKwh = pzem.energy();
  r.frequencyHz = pzem.frequency();
  r.powerFactor = pzem.pf();
  r.valid = !isnan(r.voltageV) && !isnan(r.currentA) && !isnan(r.powerW);
  return r;
}

static void postReading(const Reading &r) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Skipping post, WiFi not connected");
    return;
  }

  if (!r.valid) {
    Serial.println("PZEM read invalid (check wiring/module power), skipping post");
    return;
  }

  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["ts"] = (uint64_t)millis(); // Pi aggregator stamps authoritative receive time too
  doc["voltage_v"] = r.voltageV;
  doc["current_a"] = r.currentA;
  doc["power_w"] = r.powerW;
  doc["energy_kwh"] = r.energyKwh;
  doc["frequency_hz"] = r.frequencyHz;
  doc["power_factor"] = r.powerFactor;

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
  pzemSerial.begin(9600);
  connectWiFi();
}

void loop() {
  connectWiFi();

  Reading r = readPzem();
  postReading(r);

  delay(SAMPLE_INTERVAL_MS);
}
