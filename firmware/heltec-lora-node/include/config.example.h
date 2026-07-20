#pragma once

// Copy this file to config.h (gitignored) and fill in real values.

// Unique identifier for this device, becomes the InfluxDB device_id tag.
// Transmitted as a fixed 16-byte field (including null terminator) - keep
// it to 15 characters or fewer.
#define DEVICE_ID "kitchen-lora-01"

// How often to take a reading and transmit it, in milliseconds. LoRa is
// duty-cycle limited (EU868: typically 1% in the main sub-band), and a
// higher spreading factor (better range) means longer time-on-air per
// packet, so this needs to be longer than the WiFi firmware's 10s default.
// The value below is a conservative starting point for SF9/125kHz/38-byte
// payloads - if you change LORA_SPREADING_FACTOR or LORA_BANDWIDTH_KHZ,
// recompute time-on-air (e.g. with a LoRa airtime calculator) and adjust
// this to stay within your region's duty-cycle limit.
#define SAMPLE_INTERVAL_MS 60000

// --- LoRa radio parameters (EU868 defaults) ---
// Verify these against your region's regulations before deploying -
// frequency plans, max EIRP, and duty-cycle limits vary by country.
#define LORA_FREQUENCY_MHZ 868.0
#define LORA_BANDWIDTH_KHZ 125.0
#define LORA_SPREADING_FACTOR 9
#define LORA_CODING_RATE 5      // 4/5
#define LORA_TX_POWER_DBM 14    // EU868 main sub-band (863-870MHz) limit is +14dBm ERP in most cases
