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
    local_sensor_device_id: str
    local_sensor_serial_port: str
    local_sensor_slave_addr: int
    local_sensor_poll_interval_seconds: float
    data_retention_days: int
    readings_log_max_rows: int


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
        local_sensor_device_id=os.environ.get("LOCAL_SENSOR_DEVICE_ID", "pi-local"),
        local_sensor_serial_port=os.environ.get("LOCAL_SENSOR_SERIAL_PORT", "/dev/ttyUSB0"),
        local_sensor_slave_addr=int(os.environ.get("LOCAL_SENSOR_SLAVE_ADDR", "0xF8"), 0),
        local_sensor_poll_interval_seconds=float(os.environ.get("LOCAL_SENSOR_POLL_INTERVAL_SECONDS", "10")),
        data_retention_days=int(os.environ.get("DATA_RETENTION_DAYS", "365")),
        readings_log_max_rows=int(os.environ.get("READINGS_LOG_MAX_ROWS", "10000")),
    )
