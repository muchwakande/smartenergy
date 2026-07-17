from __future__ import annotations

import sqlite3
import threading

_lock = threading.Lock()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            ts INTEGER NOT NULL,
            voltage_v REAL NOT NULL,
            current_a REAL NOT NULL,
            power_w REAL NOT NULL,
            energy_kwh REAL NOT NULL,
            frequency_hz REAL NOT NULL,
            power_factor REAL NOT NULL,
            received_at INTEGER NOT NULL
        )
        """
    )
    # Unlike pending_readings (drained/deleted once forwarded), this table
    # is append-only and never trimmed, so "last N readings" can be served
    # regardless of forward status.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS readings_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            ts INTEGER NOT NULL,
            voltage_v REAL NOT NULL,
            current_a REAL NOT NULL,
            power_w REAL NOT NULL,
            energy_kwh REAL NOT NULL,
            frequency_hz REAL NOT NULL,
            power_factor REAL NOT NULL,
            received_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def enqueue(conn: sqlite3.Connection, reading: dict, received_at: int) -> None:
    with _lock:
        conn.execute(
            "INSERT INTO pending_readings "
            "(device_id, ts, voltage_v, current_a, power_w, energy_kwh, frequency_hz, power_factor, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reading["device_id"],
                reading["ts"],
                reading["voltage_v"],
                reading["current_a"],
                reading["power_w"],
                reading["energy_kwh"],
                reading["frequency_hz"],
                reading["power_factor"],
                received_at,
            ),
        )
        conn.commit()


def log_reading(conn: sqlite3.Connection, reading: dict, received_at: int) -> None:
    with _lock:
        conn.execute(
            "INSERT INTO readings_log "
            "(device_id, ts, voltage_v, current_a, power_w, energy_kwh, frequency_hz, power_factor, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reading["device_id"],
                reading["ts"],
                reading["voltage_v"],
                reading["current_a"],
                reading["power_w"],
                reading["energy_kwh"],
                reading["frequency_hz"],
                reading["power_factor"],
                received_at,
            ),
        )
        conn.commit()


def fetch_recent(conn: sqlite3.Connection, limit: int, device_id: str | None = None):
    with _lock:
        if device_id:
            cur = conn.execute(
                "SELECT device_id, ts, voltage_v, current_a, power_w, energy_kwh, frequency_hz, power_factor, received_at "
                "FROM readings_log WHERE device_id = ? ORDER BY id DESC LIMIT ?",
                (device_id, limit),
            )
        else:
            cur = conn.execute(
                "SELECT device_id, ts, voltage_v, current_a, power_w, energy_kwh, frequency_hz, power_factor, received_at "
                "FROM readings_log ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return cur.fetchall()


def fetch_batch(conn: sqlite3.Connection, limit: int):
    with _lock:
        cur = conn.execute(
            "SELECT id, device_id, ts, voltage_v, current_a, power_w, energy_kwh, frequency_hz, power_factor, received_at "
            "FROM pending_readings ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()


def delete_ids(conn: sqlite3.Connection, ids: list) -> None:
    if not ids:
        return
    with _lock:
        qmarks = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM pending_readings WHERE id IN ({qmarks})", ids)
        conn.commit()


def pending_count(conn: sqlite3.Connection) -> int:
    with _lock:
        cur = conn.execute("SELECT COUNT(*) FROM pending_readings")
        return cur.fetchone()[0]
