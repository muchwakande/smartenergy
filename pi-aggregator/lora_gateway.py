from __future__ import annotations

import logging
import struct
import threading
import time

from LoRaRF import SX126x

import forward_queue
from config import Config
from sd_logger import SdLogger

logger = logging.getLogger("lora_gateway")

# Must match firmware/heltec-lora-node/src/main.cpp's packed LoraReading
# struct exactly (little-endian) - update both together if this changes.
_PACKET_FORMAT = "<16sIhiiihh"
_PACKET_SIZE = struct.calcsize(_PACKET_FORMAT)


def decode_packet(data: bytes) -> dict:
    """Decodes one LoRa packet into the same reading shape used elsewhere
    in the pipeline (matches the /ingest JSON schema's field names)."""
    if len(data) != _PACKET_SIZE:
        raise ValueError(f"expected {_PACKET_SIZE} bytes, got {len(data)}")

    (
        device_id_raw,
        uptime_ms,
        voltage_dv,
        current_ma,
        power_dw,
        energy_wh,
        freq_dhz,
        pf_c,
    ) = struct.unpack(_PACKET_FORMAT, data)
    device_id = device_id_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    return {
        "device_id": device_id,
        "ts": uptime_ms,
        "voltage_v": voltage_dv / 10.0,
        "current_a": current_ma / 1000.0,
        "power_w": power_dw / 10.0,
        "energy_kwh": energy_wh / 1000.0,
        "frequency_hz": freq_dhz / 10.0,
        "power_factor": pf_c / 100.0,
    }


class LoraGatewayHandler:
    """Optional SX1262 LoRa gateway radio wired directly into the Pi.

    Off by default (the radio is optional hardware that may not be
    plugged in) and toggled independently via start()/stop(), same
    pattern as LocalSensorHandler. When running, it continuously listens
    for packets from LoRa sensor nodes (firmware/heltec-lora-node) and
    feeds them into the same archive + forward-queue path as NodeMCU
    ingests.
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
        """Starts the receive thread. Returns False if already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Stops the receive thread. Returns False if it wasn't running."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._stop_event.set()
            thread = self._thread

        thread.join(timeout=10)
        with self._lock:
            self._thread = None
        return True

    def _open_radio(self) -> SX126x:
        radio = SX126x()
        radio.setSPI(self._cfg.lora_spi_bus, self._cfg.lora_spi_cs, 7800000)
        radio.setPins(
            self._cfg.lora_reset_pin,
            self._cfg.lora_busy_pin,
            self._cfg.lora_dio1_pin,
            self._cfg.lora_txen_pin,
            self._cfg.lora_rxen_pin,
        )
        if not radio.begin():
            raise RuntimeError("SX126x.begin() failed - check wiring/SPI bus/CS config")

        radio.setFrequency(int(self._cfg.lora_frequency_mhz * 1_000_000))
        radio.setLoRaModulation(
            self._cfg.lora_spreading_factor,
            int(self._cfg.lora_bandwidth_khz * 1000),
            self._cfg.lora_coding_rate,
            False,
        )
        radio.setRxGain(radio.RX_GAIN_POWER_SAVING)
        return radio

    def _run(self) -> None:
        logger.info(
            "LoRa gateway starting (SPI bus=%s cs=%s)",
            self._cfg.lora_spi_bus,
            self._cfg.lora_spi_cs,
        )
        try:
            radio = self._open_radio()
        except Exception as exc:
            logger.error("LoRa gateway failed to start: %s", exc)
            self.last_error = str(exc)
            return

        while not self._stop_event.is_set():
            try:
                radio.request(0)  # RX_SINGLE: receive one packet
                if not radio.wait(2):  # 2s poll so stop_event is checked promptly
                    continue

                n = radio.available()
                if n <= 0:
                    continue

                data = bytes(radio.read(n))
                reading = decode_packet(data)
                received_at = int(time.time())

                self._archive.log(reading, received_at)
                forward_queue.enqueue(self._conn, reading, received_at)
                forward_queue.log_reading(self._conn, reading, received_at, self._cfg.readings_log_max_rows)

                self.last_reading_at = received_at
                self.last_error = None
                logger.info("Received LoRa reading from %s", reading["device_id"])
            except Exception as exc:
                logger.warning("LoRa receive failed: %s", exc)
                self.last_error = str(exc)

        logger.info("LoRa gateway stopped")
