import csv
import glob
import os
from datetime import datetime, timedelta, timezone

_HEADER = [
    "received_at_iso",
    "device_id",
    "ts",
    "voltage_v",
    "current_a",
    "power_w",
    "energy_kwh",
    "frequency_hz",
    "power_factor",
]


class SdLogger:
    """Append-only local archive on the Pi's SD card, one file per day.

    Independent of the forward queue: readings are logged here on ingest
    regardless of whether/when they make it to the cloud, so the recent
    history survives extended cloud outages. Bounded by retention_days
    (SD cards are finite) - whole daily files older than that are pruned,
    checked once per day (when a new day's file is first created) rather
    than on every ingest.
    """

    def __init__(self, data_dir: str, retention_days: int = 365):
        self.data_dir = data_dir
        self.retention_days = retention_days
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
                    reading["voltage_v"],
                    reading["current_a"],
                    reading["power_w"],
                    reading["energy_kwh"],
                    reading["frequency_hz"],
                    reading["power_factor"],
                ]
            )

        if is_new:
            self._prune_old_files(received_at)

    def _prune_old_files(self, received_at: int) -> None:
        cutoff = datetime.fromtimestamp(received_at, tz=timezone.utc) - timedelta(days=self.retention_days)
        for path in glob.glob(os.path.join(self.data_dir, "readings-*.csv")):
            name = os.path.basename(path)
            date_part = name[len("readings-") : -len(".csv")]
            try:
                file_day = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if file_day < cutoff:
                os.remove(path)
