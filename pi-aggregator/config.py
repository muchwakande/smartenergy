import os
from dataclasses import dataclass


@dataclass
class Config:
    api_key: str
    listen_port: int
    db_path: str
    data_dir: str
    cloud_influx_url: str
    cloud_influx_token: str
    cloud_influx_org: str
    cloud_influx_bucket: str
    forward_batch_size: int
    forward_poll_interval_seconds: float
    forward_min_backoff_seconds: float
    forward_max_backoff_seconds: float


def load_config() -> Config:
    return Config(
        api_key=os.environ["PI_API_KEY"],
        listen_port=int(os.environ.get("LISTEN_PORT", "8080")),
        db_path=os.environ.get("DB_PATH", "/data/queue.sqlite3"),
        data_dir=os.environ.get("DATA_DIR", "/data/archive"),
        cloud_influx_url=os.environ["CLOUD_INFLUX_URL"],
        cloud_influx_token=os.environ["CLOUD_INFLUX_TOKEN"],
        cloud_influx_org=os.environ["CLOUD_INFLUX_ORG"],
        cloud_influx_bucket=os.environ["CLOUD_INFLUX_BUCKET"],
        forward_batch_size=int(os.environ.get("FORWARD_BATCH_SIZE", "100")),
        forward_poll_interval_seconds=float(os.environ.get("FORWARD_POLL_INTERVAL_SECONDS", "5")),
        forward_min_backoff_seconds=float(os.environ.get("FORWARD_MIN_BACKOFF_SECONDS", "2")),
        forward_max_backoff_seconds=float(os.environ.get("FORWARD_MAX_BACKOFF_SECONDS", "300")),
    )
