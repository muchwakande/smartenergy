#pragma once

// Copy this file to config.h (gitignored) and fill in real values.

#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// Pi aggregator endpoint - found automatically via mDNS (_smartenergy._tcp)
// at boot, so these are only used as a fallback if that discovery fails
// (e.g. multicast blocked on the network, or avahi-daemon not running on
// the Pi). Still worth setting to a real reachable value.
#define PI_HOST "192.168.1.50"
#define PI_PORT 8080
#define PI_API_KEY "change-me-shared-secret"

// Unique identifier for this device, becomes the InfluxDB device_id tag
#define DEVICE_ID "kitchen-01"

// How often to take a reading and POST it, in milliseconds
#define SAMPLE_INTERVAL_MS 10000
