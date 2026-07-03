import csv
import os
from datetime import datetime, timezone

_HEADER = [
    "received_at_iso",
    "device_id",
    "ts",
    "current_rms_a",
    "power_va_approx",
    "assumed_voltage_v",
]


class SdLogger:
    """Permanent, append-only local archive on the Pi's SD card.

    Independent of the forward queue: readings are logged here on ingest
    regardless of whether/when they make it to the cloud, and are never
    deleted, so the full history survives extended cloud outages.
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def log(self, reading: dict, received_at: int) -> None:
        day = datetime.fromtimestamp(received_at, tz=timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(self.data_dir, f"readings-{day}.csv")
        is_new = not os.path.exists(path)

        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(_HEADER)
            writer.writerow(
                [
                    datetime.fromtimestamp(received_at, tz=timezone.utc).isoformat(),
                    reading["device_id"],
                    reading["ts"],
                    reading["current_rms_a"],
                    reading["power_va_approx"],
                    reading["assumed_voltage_v"],
                ]
            )
