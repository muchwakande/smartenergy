import logging
import threading
import time

from flask import Flask, jsonify, request

import forward_queue
import forwarder
from config import load_config
from sd_logger import SdLogger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

cfg = load_config()
conn = forward_queue.get_connection(cfg.db_path)
forward_queue.init_db(conn)
archive = SdLogger(cfg.data_dir)

_stop_event = threading.Event()
_forwarder_thread = threading.Thread(
    target=forwarder.run_forever,
    args=(conn, cfg, _stop_event),
    daemon=True,
)
_forwarder_thread.start()

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
    return jsonify(status="ok", pending_forward=forward_queue.pending_count(conn))


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

    return jsonify(status="accepted"), 202


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=cfg.listen_port)
