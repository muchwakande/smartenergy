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

**Note on the energy counter**: `energy_kwh` is a cumulative counter tallied
inside the PZEM-004T module itself, not by the firmware — it keeps counting
across NodeMCU reboots, but resets to zero if the module itself loses power
(some modules support a reset via a physical button or Modbus command; see
your module's datasheet).

## Repo layout

- `firmware/nodemcu-current-monitor/` — PlatformIO project for the ESP8266
- `pi-aggregator/` — Flask ingest service + SQLite forward-queue + SD card archive
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
warning over serial; check the wiring and that the module has mains power.

This firmware was written and reviewed here but **not compiled or flashed** —
PlatformIO isn't available in this environment. Run `pio run` yourself before
flashing to catch any build errors (including confirming the exact PlatformIO
registry name/version for the PZEM004Tv30 library resolves correctly), and
verify against real hardware.

## 2. Pi aggregator

Runs on the Raspberry Pi, on the home network.

```bash
cd pi-aggregator
mkdir -p data
docker compose --env-file ../.env up -d --build
curl localhost:8080/healthz
```

- `POST /ingest` (used by NodeMCUs) requires header `X-Api-Key: <PI_API_KEY>`
  and JSON body `{"device_id", "ts", "voltage_v", "current_a", "power_w", "energy_kwh", "frequency_hz", "power_factor"}`.
- Permanent archive: `pi-aggregator/data/archive/readings-YYYY-MM-DD.csv`
  (one row per ingested reading, never deleted by the app).
- Forward queue: `pi-aggregator/data/queue.sqlite3` (rows deleted only once
  successfully written to the cloud).

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

If running the aggregator via Docker Compose, the container needs access
to the adapter's serial device. Uncomment the `devices:` block in
`pi-aggregator/docker-compose.yml`, matching the path to your adapter
(`ls /dev/ttyUSB*` on the Pi to find it), then recreate the container:

```bash
docker compose --env-file ../.env up -d --build
```

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
