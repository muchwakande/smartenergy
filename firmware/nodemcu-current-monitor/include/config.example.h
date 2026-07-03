#pragma once

// Copy this file to config.h (gitignored) and fill in real values.

#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// Pi aggregator endpoint
#define PI_HOST "192.168.1.50"
#define PI_PORT 8080
#define PI_API_KEY "change-me-shared-secret"

// Unique identifier for this device, becomes the InfluxDB device_id tag
#define DEVICE_ID "kitchen-01"

// How often to take a reading and POST it, in milliseconds
#define SAMPLE_INTERVAL_MS 10000

// Assumed nominal mains voltage, used only to compute an approximate
// apparent power (current-only CT clamp has no real voltage/phase reference)
#define ASSUMED_VOLTAGE_V 230.0

// SCT-013 calibration: amps-per-volt at the ADC pin, after any onboard
// divider. Depends on your specific clamp (turns ratio) and burden
// resistor value. Start with the value printed on the clamp's datasheet,
// then refine by comparing against a known load (e.g. a kettle) once
// hardware is wired up.
#define CT_CALIBRATION 30.0
