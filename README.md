# Smart Energy Usage Monitoring

Monitors electrical usage using a PZEM-004T voltage/current sensor on a
NodeMCU, relayed through a Raspberry Pi to a cloud dashboard reachable from
anywhere.

## Architecture

```
[PZEM-004T sensor] --serial (Modbus-RTU)--> [NodeMCU] --HTTP POST--> [Raspberry Pi aggregator]
                                                                            |
                                                    +-----------------------+-----------------------+
                                                    |                                                |
                                           SD card CSV archive                             forwards batches over
                                           (permanent, never deleted)                      HTTPS to cloud InfluxDB
                                                                                                     |
                                                                                           [Cloud VPS: Caddy (TLS)
                                                                                            -> InfluxDB + Grafana]
```

- **NodeMCU**: polls the PZEM-004T over a serial (Modbus-RTU) connection for
  voltage, current, active power, cumulative energy, frequency, and power
  factor, then POSTs a JSON reading to the Pi every ~10s. No MQTT client, no
  local buffering — that's the Pi's job.
- **Pi aggregator**: accepts readings over HTTP, immediately (a) appends them to a
  permanent CSV log on the SD card, and (b) queues them in SQLite for forwarding.
  A background thread drains the queue to the cloud, retrying with backoff if the
  internet or cloud is down. The SD card archive is never deleted, so the full
  history survives even a prolonged cloud outage.
- **Cloud**: a VPS running InfluxDB (time-series storage) + Grafana (dashboard),
  behind Caddy for automatic HTTPS, so you can check usage from anywhere.

This is the default configuration; two others feed the same Pi aggregator
and can run alongside it: a PZEM wired directly into the Pi (no NodeMCU),
and an ESP32+LoRa sensor node for sites without WiFi coverage — see
"Optional: a PZEM-004T wired directly into the Pi" and "Optional: LoRa
sensor nodes" under the Pi aggregator section below.

**Note on the energy counter**: `energy_kwh` is a cumulative counter tallied
inside the PZEM-004T module itself, not by the firmware — it keeps counting
across NodeMCU reboots, but resets to zero if the module itself loses power
(some modules support a reset via a physical button or Modbus command; see
your module's datasheet).

## Repo layout

- `firmware/nodemcu-current-monitor/` — PlatformIO project for the ESP8266 (WiFi)
- `firmware/heltec-lora-node/` — PlatformIO project for an ESP32+LoRa sensor node
- `pi-aggregator/` — Flask ingest service + SQLite forward-queue + SD card archive,
  deployed on the Pi as a native systemd service (no Docker on the Pi)
- `cloud/` — Docker Compose stack for the VPS (InfluxDB, Grafana, Caddy)

## 1. Firmware

Hardware: PZEM-004T module wired into the circuit you want to monitor (mains
L/N to the module's voltage terminals, live wire through the module's current
sensing — either direct in-line wiring or an external split-core CT clamp,
depending on your module variant), with its TTL serial pins connected to the
NodeMCU over `SoftwareSerial`: PZEM `TX` -> NodeMCU `D2`, PZEM `RX` -> NodeMCU
`D1` (through a level shifter/voltage divider if your module's logic level is
5V). **Wiring the module's mains-side terminals is line-voltage work — treat
it with the same care as any mains wiring, and double check your specific
module's datasheet before connecting anything.**

**Power the PZEM's TTL-side VCC from NodeMCU's `3V3` pin, not `VU`/`VIN`.**
`VU`/`VIN` is raw, unregulated 5V tapped straight off the USB cable, and can
be noisy enough (particularly during WiFi radio current spikes) to disrupt
the PZEM module's own internal MCU — this presents as the module never
responding on the serial link at all (reads consistently come back `NAN`),
even though wiring, voltage level, and protocol are all otherwise correct.
NodeMCU's onboard `3V3` regulator output is clean and has been confirmed to
work reliably; `VU` has been confirmed to cause total communication failure
despite passing every other check (continuity, correct TX/RX crossing,
correct protocol/library, correct CRC).

```bash
cd firmware/nodemcu-current-monitor
cp include/config.example.h include/config.h
# edit config.h: WiFi credentials, Pi host/port, API key, device_id
pio run -t upload   # requires PlatformIO CLI (pio) installed locally
pio device monitor
```

The PZEM-004T reports calibrated voltage/current/power directly — there's no
software calibration constant to tune, unlike a CT-clamp setup. If readings
come back invalid (`NAN`), the firmware skips posting that cycle and logs a
warning over serial; check the wiring, that the module has mains power, and
— the most common real-world cause — that the PZEM's VCC is powered from
NodeMCU's `3V3` pin and not `VU`/`VIN` (see above).

This firmware has been built, flashed, and verified end-to-end against real
hardware (WiFi join, PZEM read, HTTP POST to the Pi, all confirmed working).

### Finding the Pi automatically (mDNS)

The NodeMCU doesn't need a hardcoded Pi IP. At boot (and again if a POST
ever fails) it queries mDNS/DNS-SD for `_smartenergy._tcp`, which the Pi
aggregator advertises automatically (see below) — no config needed beyond
what's already in `config.h`. `PI_HOST`/`PI_PORT` are kept only as a
fallback for networks where multicast is blocked or the Pi isn't running
avahi; verified working via `MDNS.queryService("smartenergy", "tcp")`.

## 2. Pi aggregator

Runs directly on the Raspberry Pi (no Docker), on the home network, as a
systemd service.

```bash
# on the Pi:
git clone <this-repo-url> ~/smartenergy
cd ~/smartenergy
cp .env.example .env
# edit .env: PI_API_KEY, CLOUD_INFLUX_* (and LOCAL_SENSOR_* if using the
# optional local sensor below)
./pi-aggregator/deploy/install.sh
curl localhost:8080/healthz
```

`install.sh` creates a venv under `pi-aggregator/.venv`, installs
`requirements.txt` into it, and installs+starts a systemd unit
(`smartenergy-aggregator.service`) running gunicorn with a single worker
(the forwarder and local-sensor background threads must not be started more
than once). It also advertises the aggregator over mDNS/DNS-SD as
`_smartenergy._tcp` on `LISTEN_PORT` (default 8080), via a static service
file (`deploy/smartenergy-aggregator.avahi-service`) installed to
`/etc/avahi/services/` — this is what NodeMCUs discover automatically
(see the firmware section above). Relies on `avahi-daemon`, which ships
enabled by default on Raspberry Pi OS; `install.sh` installs it only if
somehow missing. Verify it's working with:

```bash
avahi-browse -rt _smartenergy._tcp
```

Re-run `install.sh` after `git pull` to redeploy. Useful commands:

```bash
sudo systemctl status smartenergy-aggregator
sudo journalctl -u smartenergy-aggregator -f
sudo systemctl restart smartenergy-aggregator
```

- `POST /ingest` (used by NodeMCUs) requires header `X-Api-Key: <PI_API_KEY>`
  and JSON body `{"device_id", "ts", "voltage_v", "current_a", "power_w", "energy_kwh", "frequency_hz", "power_factor"}`.
- `GET /readings?n=10&device_id=kitchen-01` requires header
  `X-Api-Key: <PI_API_KEY>`. Returns the most recent `n` readings (default
  10, max 500), newest first, optionally filtered to one `device_id`:
  ```bash
  curl "localhost:8080/readings?n=10" -H "X-Api-Key: $PI_API_KEY"
  ```
- SD card archive: `pi-aggregator/data/archive/readings-YYYY-MM-DD.csv`,
  one file per day. Kept for `DATA_RETENTION_DAYS` (default 365, sized for
  a 64GB card); whole daily files older than that are deleted.
- Forward queue: `pi-aggregator/data/queue.sqlite3` (rows deleted only once
  successfully written to the cloud). A separate `readings_log` table in
  the same SQLite file backs `/readings` and is capped at
  `READINGS_LOG_MAX_ROWS` (default 10000, oldest rows pruned on insert) -
  it's a recent-readings view, not a long-term archive.

### Optional: a PZEM-004T wired directly into the Pi

In addition to (or instead of) NodeMCU-connected sensors, one PZEM-004T can
be wired straight into the Pi over a USB-to-TTL serial adapter (e.g. a
CP2102 or CH340 module) — useful for monitoring whatever circuit the Pi
itself is near, without a separate microcontroller.

Wiring: PZEM `TX` -> adapter `RX`, PZEM `RX` -> adapter `TX`, PZEM `GND` ->
adapter `GND`, PZEM `5V` -> adapter `5V` (check your adapter can source
enough current, or power the PZEM separately). The adapter plugs into the
Pi's USB port. As with the NodeMCU wiring, connecting the module's
mains-side terminals is line-voltage work — treat it accordingly.

Find the adapter's device path with `ls /dev/ttyUSB*` on the Pi and set
`LOCAL_SENSOR_SERIAL_PORT` in `.env` accordingly (default `/dev/ttyUSB0`).
Since the aggregator runs natively (not in a container), no device
passthrough is needed — `install.sh` already adds the service user to the
`dialout` group for serial port access; log out/in (or reboot) once after
the first install for that to take effect.

This local sensor is **off by default** — it's optional hardware that may
not be plugged in — and is controlled independently of the rest of the
pipeline via three endpoints, authenticated the same way as `/ingest`:

```bash
curl -X POST localhost:8080/local-sensor/start -H "X-Api-Key: $PI_API_KEY"
curl localhost:8080/local-sensor/status -H "X-Api-Key: $PI_API_KEY"
curl -X POST localhost:8080/local-sensor/stop -H "X-Api-Key: $PI_API_KEY"
```

Once started, it polls the sensor every `LOCAL_SENSOR_POLL_INTERVAL_SECONDS`
(default 10s) and feeds readings into the exact same archive + forward-queue
path as NodeMCU ingests, tagged with `LOCAL_SENSOR_DEVICE_ID` (default
`pi-local`) as its `device_id`. A failed read (adapter unplugged, wiring
issue, garbled Modbus frame) is logged and retried next cycle rather than
stopping the handler — check `/local-sensor/status` for `last_error`.

This integration was written and reviewed here but **not tested against
real hardware** — the PZEM-004T Modbus-RTU register map it relies on is
well documented, but verify readings against a known load once wired up.

### Optional: LoRa sensor nodes (long range, no WiFi)

A third sensor configuration, alongside the WiFi NodeMCU and the Pi-local
PZEM above: for sites where WiFi coverage doesn't reach (large sites,
sensors spread across separate buildings), a sensor node can talk to the
Pi over LoRa instead. It's not a replacement for the WiFi path — all three
configurations can run at once, feeding the same pipeline.

```
[PZEM-004T] --serial--> [ESP32 + LoRa node] --LoRa--> [Pi + LoRa gateway radio] --> same archive/forward-queue path
```

**Node hardware**: an ESP32 board with onboard LoRa (developed against the
Heltec WiFi LoRa 32 V3, SX1262 radio) rather than a NodeMCU + external LoRa
module — this also gets a real hardware UART for the PZEM instead of
`SoftwareSerial` (ESP32 has multiple UARTs, and this board's USB/debug
console uses separate pins from the ones used here). Firmware:
`firmware/heltec-lora-node/`. PZEM wiring: `TX -> GPIO5`, `RX -> GPIO6`
(verify these and the LoRa SPI pins in `src/main.cpp` against your exact
board revision — Heltec has several similarly-named boards with different
pin maps). Build/flash the same way as the NodeMCU firmware:

```bash
cd firmware/heltec-lora-node
cp include/config.example.h include/config.h
# edit config.h: device_id, LoRa radio parameters
pio run -t upload
```

**Gateway hardware**: an SX1262 LoRa module/HAT wired to the Pi's SPI bus
and GPIO header (e.g. reset/busy/DIO1/TXEN/RXEN lines) — the pin defaults
in `.env.example` match `LoRaRF`'s own Raspberry Pi example wiring, not any
specific HAT, so verify against your exact module's documentation. SPI is
disabled by default on a fresh Raspberry Pi OS install - enable it with
`sudo raspi-config` (Interface Options -> SPI) and reboot before using
this. Started the same way as the local PZEM sensor, via `/lora-gateway/*`:

```bash
curl -X POST localhost:8080/lora-gateway/start -H "X-Api-Key: $PI_API_KEY"
curl localhost:8080/lora-gateway/status -H "X-Api-Key: $PI_API_KEY"
curl -X POST localhost:8080/lora-gateway/stop -H "X-Api-Key: $PI_API_KEY"
```

**Protocol**: LoRa's payload budget and duty-cycle limits make JSON
impractical, so nodes send a compact 38-byte fixed-point binary encoding
(`LoraReading` struct in `main.cpp`, decoded by `lora_gateway.py`'s
`decode_packet` — the two must stay in sync; a `static_assert` on the
firmware side guards against silent struct-size drift) instead of the
`/ingest` JSON schema. Field resolutions match the PZEM's own native
register resolutions, so no precision is lost.

**Duty cycle / regulatory**: defaults target EU868 at SF9/125kHz, with a
conservative 60s transmit interval — if you change the spreading factor,
bandwidth, or region, recompute time-on-air (e.g. with an online LoRa
airtime calculator) and adjust the interval and `LORA_TX_POWER_DBM` to
stay within your region's limits.

This configuration was written and reviewed here but **not tested against
real radios** — no LoRa hardware was available to verify against. What
*has* been verified: the firmware builds cleanly for the
`heltec_wifi_lora_32_V3` board, and the binary packet encoding/decoding
round-trips correctly byte-for-byte between the C++ struct and Python
`struct.unpack` (matching field values exactly). `LoRaRF` also refuses to
import outside a real Raspberry Pi (it hard-checks for one), so
`lora_gateway.py` can only be smoke-tested once deployed there with the
radio wired up.

## 3. Cloud stack

Runs on a public VPS. Requires a domain name with a DNS A record pointing at
the VPS's IP, so Caddy can obtain a Let's Encrypt certificate automatically.

```bash
cd cloud
docker compose --env-file ../.env up -d
```

- Dashboard: `https://<CLOUD_DOMAIN>/grafana/` (login with `admin` /
  `GRAFANA_ADMIN_PASSWORD`).
- Ingest endpoint the Pi forwards to: `https://<CLOUD_DOMAIN>/api/v2/write`.

If you don't have a domain yet, you can still bring the stack up and reach it
over plain `http://<vps-ip>` for local testing — but do **not** leave it
exposed to the public internet without TLS, since the InfluxDB token and
Grafana login would travel in the clear. Get a domain and TLS working before
relying on this for anything beyond a quick test.

If you change `CLOUD_INFLUX_BUCKET` away from the default `energy`, also
update the bucket name inside
`cloud/grafana/dashboards/energy-overview.json` (hardcoded there for
simplicity).

## Testing the pipeline without hardware

1. Bring up the cloud stack (`cloud/`) and the Pi aggregator (`pi-aggregator/`),
   both pointed at the same `.env`.
2. Send a fake reading into the Pi:
   ```bash
   curl -X POST localhost:8080/ingest \
     -H "X-Api-Key: $PI_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"device_id":"test-01","ts":1234567890,"voltage_v":231.2,"current_a":3.1,"power_w":702,"energy_kwh":12.4,"frequency_hz":50.0,"power_factor":0.98}'
   ```
3. Confirm it's queued: `curl localhost:8080/healthz` should show
   `pending_forward` briefly non-zero, then 0 once forwarded.
4. Confirm it's archived: check
   `pi-aggregator/data/archive/readings-<today>.csv`.
5. Confirm it reached the cloud: check the Grafana dashboard, or query
   InfluxDB directly.

**Offline resilience check**: stop the cloud stack, POST another reading to
the Pi, confirm `pending_forward` stays non-zero and a new CSV row still
appears. Restart the cloud stack and confirm the queue drains.
