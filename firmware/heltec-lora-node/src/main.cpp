#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <PZEM004Tv30.h>

#include "config.h"

// PZEM-004T over a dedicated hardware UART. ESP32-S3's UART0 (the default
// Serial object) is wired to the onboard USB-serial bridge for
// flashing/debug, so PZEM gets its own UART on free GPIOs instead - see
// https://wiki.heltec.org (GPIO Usage Guide) for this board's reserved
// pins (OLED, JTAG, SPI flash, USB) before changing these.
static const int PZEM_RX_PIN = 5;
static const int PZEM_TX_PIN = 6;
HardwareSerial pzemSerial(1);
PZEM004Tv30 pzem(pzemSerial, PZEM_RX_PIN, PZEM_TX_PIN);

// SX1262 LoRa radio wiring for the Heltec WiFi LoRa 32 V3 (confirmed
// against Heltec's schematic/examples - verify against your exact board
// revision before flashing, since Heltec has several similarly-named
// boards with different pin maps).
#define LORA_NSS 8
#define LORA_DIO1 14
#define LORA_RST 12
#define LORA_BUSY 13
#define LORA_SCK 9
#define LORA_MISO 11
#define LORA_MOSI 10

SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY);

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

// Compact fixed-point binary encoding (38 bytes) instead of JSON - LoRa's
// payload budget and duty-cycle limits make a text encoding wasteful.
// Field resolutions match the PZEM's own native register resolutions, so
// no precision is lost. The gateway (pi-aggregator/lora_gateway.py) must
// decode with the exact same layout - keep the two in sync if this changes.
#pragma pack(push, 1)
struct LoraReading {
  char deviceId[16];      // null-terminated
  uint32_t uptimeMs;      // millis() at time of reading
  int16_t voltageDv;      // volts * 10
  int32_t currentMa;      // amps * 1000
  int32_t powerDw;        // watts * 10
  int32_t energyWh;       // kWh * 1000
  int16_t frequencyDhz;   // hz * 10
  int16_t powerFactorC;   // power factor * 100
};
#pragma pack(pop)

static_assert(sizeof(LoraReading) == 38, "LoraReading size drifted from what lora_gateway.py's _PACKET_FORMAT expects");

static void encodeReading(const Reading &r, LoraReading &out) {
  memset(&out, 0, sizeof(out));
  strncpy(out.deviceId, DEVICE_ID, sizeof(out.deviceId) - 1);
  out.uptimeMs = millis();
  out.voltageDv = (int16_t)(r.voltageV * 10 + 0.5f);
  out.currentMa = (int32_t)(r.currentA * 1000 + 0.5f);
  out.powerDw = (int32_t)(r.powerW * 10 + 0.5f);
  out.energyWh = (int32_t)(r.energyKwh * 1000 + 0.5f);
  out.frequencyDhz = (int16_t)(r.frequencyHz * 10 + 0.5f);
  out.powerFactorC = (int16_t)(r.powerFactor * 100 + 0.5f);
}

void setup() {
  Serial.begin(115200);
  delay(200);

  pzemSerial.begin(9600, SERIAL_8N1, PZEM_RX_PIN, PZEM_TX_PIN);

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = radio.begin(LORA_FREQUENCY_MHZ, LORA_BANDWIDTH_KHZ, LORA_SPREADING_FACTOR,
                           LORA_CODING_RATE, RADIOLIB_SX126X_SYNC_WORD_PRIVATE, LORA_TX_POWER_DBM);
  if (state != RADIOLIB_ERR_NONE) {
    // If this fails on a Heltec V3 board specifically, try passing
    // useRegulatorLDO=true (the 9th argument to begin()) - some board
    // revisions need the LDO regulator rather than the DC-DC one.
    Serial.printf("Radio init failed, code %d\n", state);
  } else {
    Serial.println("Radio init OK");
  }
}

void loop() {
  Reading r = readPzem();

  if (!r.valid) {
    Serial.println("PZEM read invalid (check wiring/module power), skipping transmit");
    delay(SAMPLE_INTERVAL_MS);
    return;
  }

  LoraReading payload;
  encodeReading(r, payload);

  int state = radio.transmit((uint8_t *)&payload, sizeof(payload));
  if (state == RADIOLIB_ERR_NONE) {
    Serial.printf("LoRa transmit OK (%u bytes)\n", (unsigned)sizeof(payload));
  } else {
    Serial.printf("LoRa transmit failed, code %d\n", state);
  }

  delay(SAMPLE_INTERVAL_MS);
}
