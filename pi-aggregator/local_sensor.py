import logging
import threading
import time

from pymodbus.client import ModbusSerialClient

import forward_queue
from config import Config
from sd_logger import SdLogger

logger = logging.getLogger("local_sensor")

# PZEM-004T v3.0 Modbus-RTU input register map: voltage (1 reg, 0.1V),
# current (2 regs, 0.001A), power (2 regs, 0.1W), energy (2 regs, 1Wh),
# frequency (1 reg, 0.1Hz), power factor (1 reg, 0.01). A 10th register
# (alarm status) exists but isn't needed here.
_INPUT_REGISTER_COUNT = 9


def read_once(serial_port: str, slave_addr: int, timeout: float = 1.0) -> dict:
    """Reads one set of registers from a PZEM-004T over Modbus-RTU.

    Raises RuntimeError on any failure (port missing, device unplugged,
    garbled frame, etc.) - callers should treat that as "no reading this
    cycle", not fatal.
    """
    client = ModbusSerialClient(
        port=serial_port, baudrate=9600, bytesize=8, parity="N", stopbits=1, timeout=timeout
    )
    try:
        if not client.connect():
            raise RuntimeError(f"could not open serial port {serial_port}")

        result = client.read_input_registers(address=0x0000, count=_INPUT_REGISTER_COUNT, slave=slave_addr)
        if result.isError():
            raise RuntimeError(f"Modbus read error: {result}")

        regs = result.registers
        return {
            "voltage_v": regs[0] / 10.0,
            "current_a": (regs[1] | (regs[2] << 16)) / 1000.0,
            "power_w": (regs[3] | (regs[4] << 16)) / 10.0,
            "energy_kwh": (regs[5] | (regs[6] << 16)) / 1000.0,
            "frequency_hz": regs[7] / 10.0,
            "power_factor": regs[8] / 100.0,
        }
    finally:
        client.close()


class LocalSensorHandler:
    """Optional PZEM-004T wired directly into the Pi over USB/serial.

    Off by default (the sensor is optional hardware that may not be
    plugged in) and toggled independently of the rest of the pipeline via
    start()/stop(), so it can be enabled/disabled at runtime without
    restarting the aggregator. When running, it feeds readings into the
    same archive + forward-queue path as NodeMCU ingests.
    """

    def __init__(self, conn, archive: SdLogger, cfg: Config):
        self._conn = conn
        self._archive = archive
        self._cfg = cfg
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.last_reading_at: int | None = None
        self.last_error: str | None = None

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Starts the polling thread. Returns False if already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Stops the polling thread. Returns False if it wasn't running."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._stop_event.set()
            thread = self._thread

        thread.join(timeout=self._cfg.local_sensor_poll_interval_seconds + 5)
        with self._lock:
            self._thread = None
        return True

    def _run(self) -> None:
        logger.info("Local sensor handler starting (port=%s)", self._cfg.local_sensor_serial_port)
        while not self._stop_event.is_set():
            try:
                reading = read_once(self._cfg.local_sensor_serial_port, self._cfg.local_sensor_slave_addr)
                reading["device_id"] = self._cfg.local_sensor_device_id
                reading["ts"] = int(time.time() * 1000)
                received_at = int(time.time())

                self._archive.log(reading, received_at)
                forward_queue.enqueue(self._conn, reading, received_at)
                forward_queue.log_reading(self._conn, reading, received_at)

                self.last_reading_at = received_at
                self.last_error = None
            except Exception as exc:
                logger.warning("Local sensor read failed: %s", exc)
                self.last_error = str(exc)

            self._stop_event.wait(self._cfg.local_sensor_poll_interval_seconds)
        logger.info("Local sensor handler stopped")
