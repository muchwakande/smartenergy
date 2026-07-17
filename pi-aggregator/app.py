import logging
import threading
import time

from flask import Flask, jsonify, request

import forward_queue
import forwarder
import local_sensor
from config import load_config
from sd_logger import SdLogger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

cfg = load_config()
conn = forward_queue.get_connection(cfg.db_path)
forward_queue.init_db(conn)
archive = SdLogger(cfg.data_dir, cfg.data_retention_days)

_stop_event = threading.Event()
_forwarder_thread = threading.Thread(
    target=forwarder.run_forever,
    args=(conn, cfg, _stop_event),
    daemon=True,
)
_forwarder_thread.start()

# Not started here: this is optional hardware (a PZEM-004T wired directly
# into the Pi) that may not be plugged in, so it's toggled on demand via
# the /local-sensor/* endpoints below rather than always running.
local_sensor_handler = local_sensor.LocalSensorHandler(conn, archive, cfg)

app = Flask(__name__)

_REQUIRED_FIELDS = (
    "device_id",
    "ts",
    "voltage_v",
    "current_a",
    "power_w",
    "energy_kwh",
    "frequency_hz",
    "power_factor",
)


@app.get("/healthz")
def healthz():
    return jsonify(
        status="ok",
        pending_forward=forward_queue.pending_count(conn),
        local_sensor_running=local_sensor_handler.is_running(),
    )


@app.post("/local-sensor/start")
def local_sensor_start():
    if request.headers.get("X-Api-Key") != cfg.api_key:
        return jsonify(error="unauthorized"), 401
    started = local_sensor_handler.start()
    return jsonify(status="started" if started else "already_running"), 200


@app.post("/local-sensor/stop")
def local_sensor_stop():
    if request.headers.get("X-Api-Key") != cfg.api_key:
        return jsonify(error="unauthorized"), 401
    stopped = local_sensor_handler.stop()
    return jsonify(status="stopped" if stopped else "already_stopped"), 200


@app.get("/local-sensor/status")
def local_sensor_status():
    if request.headers.get("X-Api-Key") != cfg.api_key:
        return jsonify(error="unauthorized"), 401
    return jsonify(
        running=local_sensor_handler.is_running(),
        last_reading_at=local_sensor_handler.last_reading_at,
        last_error=local_sensor_handler.last_error,
    )


@app.post("/ingest")
def ingest():
    if request.headers.get("X-Api-Key") != cfg.api_key:
        return jsonify(error="unauthorized"), 401

    body = request.get_json(silent=True)
    if not body or any(field not in body for field in _REQUIRED_FIELDS):
        return jsonify(error="invalid payload"), 400

    received_at = int(time.time())

    # Permanent local archive first: this must succeed even if the forward
    # queue or cloud path has problems.
    archive.log(body, received_at)
    forward_queue.enqueue(conn, body, received_at)
    forward_queue.log_reading(conn, body, received_at, cfg.readings_log_max_rows)

    return jsonify(status="accepted"), 202


@app.get("/readings")
def readings():
    if request.headers.get("X-Api-Key") != cfg.api_key:
        return jsonify(error="unauthorized"), 401

    try:
        n = int(request.args.get("n", 10))
    except ValueError:
        return jsonify(error="invalid n"), 400
    n = max(1, min(n, 500))
    device_id = request.args.get("device_id")

    rows = forward_queue.fetch_recent(conn, n, device_id)
    fields = (
        "device_id",
        "ts",
        "voltage_v",
        "current_a",
        "power_w",
        "energy_kwh",
        "frequency_hz",
        "power_factor",
        "received_at",
    )
    return jsonify(readings=[dict(zip(fields, row)) for row in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=cfg.listen_port)
