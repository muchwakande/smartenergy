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
            current_rms_a REAL NOT NULL,
            power_va_approx REAL NOT NULL,
            assumed_voltage_v REAL NOT NULL,
            received_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def enqueue(conn: sqlite3.Connection, reading: dict, received_at: int) -> None:
    with _lock:
        conn.execute(
            "INSERT INTO pending_readings "
            "(device_id, ts, current_rms_a, power_va_approx, assumed_voltage_v, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                reading["device_id"],
                reading["ts"],
                reading["current_rms_a"],
                reading["power_va_approx"],
                reading["assumed_voltage_v"],
                received_at,
            ),
        )
        conn.commit()


def fetch_batch(conn: sqlite3.Connection, limit: int):
    with _lock:
        cur = conn.execute(
            "SELECT id, device_id, ts, current_rms_a, power_va_approx, assumed_voltage_v, received_at "
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
