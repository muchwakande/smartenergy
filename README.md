# Smart Energy Usage Monitoring

Monitors electrical current draw using a non-invasive CT clamp on a NodeMCU,
relayed through a Raspberry Pi to a cloud dashboard reachable from anywhere.

## Architecture

```
[SCT-013 CT clamp] --analog--> [NodeMCU] --HTTP POST--> [Raspberry Pi aggregator]
                                                                |
                                            +-------------------+-------------------+
                                            |                                       |
                                   SD card CSV archive                    forwards batches over
                                   (permanent, never deleted)             HTTPS to cloud InfluxDB
                                                                                    |
                                                                          [Cloud VPS: Caddy (TLS)
                                                                           -> InfluxDB + Grafana]
```

- **NodeMCU**: samples the CT clamp, computes RMS current, POSTs a JSON reading to
  the Pi every ~10s. No MQTT client, no local buffering — that's the Pi's job.
- **Pi aggregator**: accepts readings over HTTP, immediately (a) appends them to a
  permanent CSV log on the SD card, and (b) queues them in SQLite for forwarding.
  A background thread drains the queue to the cloud, retrying with backoff if the
  internet or cloud is down. The SD card archive is never deleted, so the full
  history survives even a prolonged cloud outage.
- **Cloud**: a VPS running InfluxDB (time-series storage) + Grafana (dashboard),
  behind Caddy for automatic HTTPS, so you can check usage from anywhere.

**Note on accuracy**: a CT clamp measures current only — there's no voltage/phase
reference, so true active power (W) can't be computed. Readings include an
*approximate* apparent power (`power_va_approx`) based on an assumed nominal
mains voltage; treat it as an estimate, not a wattmeter-grade figure.

## Repo layout

- `firmware/nodemcu-current-monitor/` — PlatformIO project for the ESP8266
- `pi-aggregator/` — Flask ingest service + SQLite forward-queue + SD card archive
- `cloud/` — Docker Compose stack for the VPS (InfluxDB, Grafana, Caddy)

## 1. Firmware

Hardware: SCT-013 CT clamp around one live wire of the circuit you want to
monitor, feeding a burden resistor + DC bias network into NodeMCU pin `A0`
(the bias circuit centers the AC signal within the ADC's 0-3.3V positive-only
range — a common CT clamp + burden resistor + voltage divider setup; the exact
component values depend on your specific clamp).

```bash
cd firmware/nodemcu-current-monitor
cp include/config.example.h include/config.h
# edit config.h: WiFi credentials, Pi host/port, API key, device_id, calibration
pio run -t upload   # requires PlatformIO CLI (pio) installed locally
pio device monitor
```

`CT_CALIBRATION` in `config.h` converts the ADC's RMS reading into amps. Start
with the value from your clamp's datasheet, then refine by comparing against a
known load (e.g. a kettle rated in watts, at a known voltage) once wired up.

This firmware was written and reviewed here but **not compiled or flashed** —
PlatformIO isn't available in this environment. Run `pio run` yourself before
flashing to catch any build errors, and expect to iterate on calibration with
real hardware.

## 2. Pi aggregator

Runs on the Raspberry Pi, on the home network.

```bash
cd pi-aggregator
mkdir -p data
docker compose --env-file ../.env up -d --build
curl localhost:8080/healthz
```

- `POST /ingest` (used by NodeMCUs) requires header `X-Api-Key: <PI_API_KEY>`
  and JSON body `{"device_id", "ts", "current_rms_a", "power_va_approx", "assumed_voltage_v"}`.
- Permanent archive: `pi-aggregator/data/archive/readings-YYYY-MM-DD.csv`
  (one row per ingested reading, never deleted by the app).
- Forward queue: `pi-aggregator/data/queue.sqlite3` (rows deleted only once
  successfully written to the cloud).

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
     -d '{"device_id":"test-01","ts":1234567890,"current_rms_a":3.1,"power_va_approx":713,"assumed_voltage_v":230}'
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
