#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266mDNS.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>
#include <SoftwareSerial.h>
#include <PZEM004Tv30.h>

#include "config.h"

// The Pi aggregator advertises itself over mDNS/DNS-SD as _smartenergy._tcp
// (see pi-aggregator/deploy/smartenergy-aggregator.avahi-service), so it can
// be found on the LAN without a hardcoded IP. PI_HOST/PI_PORT from config.h
// are kept as a fallback for networks where multicast is blocked or the
// aggregator isn't running avahi.
IPAddress piIp;
uint16_t piPort = PI_PORT;

static void resolvePiAddress() {
  int n = MDNS.queryService("smartenergy", "tcp");
  if (n > 0) {
    piIp = MDNS.IP(0);
    piPort = MDNS.port(0);
    Serial.printf("Resolved aggregator via mDNS: %s:%u\n", piIp.toString().c_str(), piPort);
    return;
  }

  Serial.println("mDNS discovery found nothing, falling back to configured PI_HOST");
  piIp.fromString(PI_HOST);
  piPort = PI_PORT;
}

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
  String url = String("http://") + piIp.toString() + ":" + piPort + "/ingest";

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
    Serial.printf("POST failed: %s, re-resolving aggregator address\n", http.errorToString(status).c_str());
    resolvePiAddress();
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pzemSerial.begin(9600);
  connectWiFi();
  MDNS.begin(DEVICE_ID);
  resolvePiAddress();
}

void loop() {
  connectWiFi();
  MDNS.update();

  Reading r = readPzem();
  postReading(r);

  delay(SAMPLE_INTERVAL_MS);
}
