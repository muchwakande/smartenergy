import logging
import threading

import requests

import forward_queue
from config import Config

logger = logging.getLogger("forwarder")


def _to_line_protocol(rows) -> str:
    lines = []
    for (
        _id,
        device_id,
        _ts,
        voltage_v,
        current_a,
        power_w,
        energy_kwh,
        frequency_hz,
        power_factor,
        received_at,
    ) in rows:
        tags = f"device_id={device_id}"
        fields = (
            f"voltage_v={voltage_v},"
            f"current_a={current_a},"
            f"power_w={power_w},"
            f"energy_kwh={energy_kwh},"
            f"frequency_hz={frequency_hz},"
            f"power_factor={power_factor}"
        )
        lines.append(f"energy,{tags} {fields} {received_at}")
    return "\n".join(lines)


def run_forever(conn, cfg: Config, stop_event: threading.Event) -> None:
    """Drains the forward queue to the cloud InfluxDB, retrying with backoff.

    Rows are only deleted from the queue on a confirmed successful write,
    so a cloud/network outage just accumulates a backlog that drains once
    connectivity returns (readings are never lost in this leg either, on
    top of the permanent SD card archive written at ingest time).
    """
    backoff = cfg.forward_min_backoff_seconds
    write_url = (
        f"{cfg.cloud_influx_url}/api/v2/write"
        f"?org={cfg.cloud_influx_org}&bucket={cfg.cloud_influx_bucket}&precision=s"
    )
    headers = {
        "Authorization": f"Token {cfg.cloud_influx_token}",
        "Content-Type": "text/plain; charset=utf-8",
    }

    while not stop_event.is_set():
        rows = forward_queue.fetch_batch(conn, cfg.forward_batch_size)
        if not rows:
            stop_event.wait(cfg.forward_poll_interval_seconds)
            continue

        body = _to_line_protocol(rows)
        try:
            resp = requests.post(write_url, headers=headers, data=body, timeout=10)
            if resp.status_code in (200, 204):
                forward_queue.delete_ids(conn, [r[0] for r in rows])
                backoff = cfg.forward_min_backoff_seconds
                logger.info("Forwarded %d readings to cloud", len(rows))
            else:
                logger.warning("Cloud write rejected: %s %s", resp.status_code, resp.text)
                stop_event.wait(backoff)
                backoff = min(backoff * 2, cfg.forward_max_backoff_seconds)
        except requests.RequestException as exc:
            logger.warning("Cloud unreachable: %s", exc)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, cfg.forward_max_backoff_seconds)
