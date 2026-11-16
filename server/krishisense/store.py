"""SQLite storage for readings, advice and sent alerts (one file, no server needed)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from .advisor import Advice, Reading

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    station_id TEXT NOT NULL, ts REAL NOT NULL, seq INTEGER,
    soil_raw TEXT NOT NULL, air_temp_c REAL, humidity REAL, pressure_hpa REAL, battery_v REAL,
    received_at REAL NOT NULL,
    UNIQUE (station_id, seq, ts)
);
CREATE INDEX IF NOT EXISTS idx_readings_station_ts ON readings (station_id, ts);
CREATE TABLE IF NOT EXISTS advice (
    station_id TEXT NOT NULL, created_at REAL NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    station_id TEXT NOT NULL, sent_at REAL NOT NULL, status TEXT NOT NULL, recipient TEXT, text TEXT
);
CREATE TABLE IF NOT EXISTS pump_commands (
    station_id TEXT NOT NULL, issued_at REAL NOT NULL, minutes INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path: str = "krishisense.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def add_reading(self, station_id: str, r: dict) -> bool:
        """Insert one reading; returns False for duplicates (re-sent buffers)."""
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?,?,?)",
                (station_id, float(r["ts"]), r.get("seq"), json.dumps(r["soil_raw"]),
                 r.get("air_temp_c"), r.get("humidity"), r.get("pressure_hpa"),
                 r.get("battery_v"), time.time()))
            self.conn.commit()
            return cur.rowcount == 1

    def latest_reading(self, station_id: str) -> Reading | None:
        row = self.conn.execute(
            "SELECT * FROM readings WHERE station_id=? ORDER BY ts DESC LIMIT 1", (station_id,)).fetchone()
        return None if row is None else _to_reading(row)

    def readings(self, station_id: str, limit: int = 200) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM readings WHERE station_id=? ORDER BY ts DESC LIMIT ?", (station_id, limit)).fetchall()
        return [{**dict(r), "soil_raw": json.loads(r["soil_raw"])} for r in rows]

    def temp_range(self, station_id: str, since_s: float) -> tuple[float, float] | None:
        row = self.conn.execute(
            "SELECT MIN(air_temp_c), MAX(air_temp_c) FROM readings WHERE station_id=? AND ts>=? "
            "AND air_temp_c IS NOT NULL", (station_id, since_s)).fetchone()
        return None if row[0] is None else (row[0], row[1])

    def save_advice(self, a: Advice, ts: float | None = None) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO advice VALUES (?,?,?,?)",
                              (a.station_id, ts or time.time(), a.status, json.dumps(a.to_dict())))
            self.conn.commit()

    def latest_advice(self, station_id: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM advice WHERE station_id=? ORDER BY created_at DESC LIMIT 1",
                                (station_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def last_alert(self, station_id: str, status: str | None = None) -> sqlite3.Row | None:
        if status is None:
            return self.conn.execute("SELECT * FROM alerts WHERE station_id=? ORDER BY sent_at DESC LIMIT 1",
                                     (station_id,)).fetchone()
        return self.conn.execute(
            "SELECT * FROM alerts WHERE station_id=? AND status=? ORDER BY sent_at DESC LIMIT 1",
            (station_id, status)).fetchone()

    def log_alert(self, station_id: str, status: str, recipient: str, text: str,
                  ts: float | None = None) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO alerts VALUES (?,?,?,?,?)",
                              (station_id, ts or time.time(), status, recipient, text))
            self.conn.commit()

    def last_pump_command(self, station_id: str) -> float | None:
        row = self.conn.execute("SELECT MAX(issued_at) FROM pump_commands WHERE station_id=?",
                                (station_id,)).fetchone()
        return row[0]

    def log_pump_command(self, station_id: str, minutes: int, ts: float | None = None) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO pump_commands VALUES (?,?,?)",
                              (station_id, ts or time.time(), minutes))
            self.conn.commit()


    # ---- queries for the dashboard ---------------------------------------------
    def history(self, station_id: str, since_ts: float) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM readings WHERE station_id=? AND ts>=? ORDER BY ts", (station_id, since_ts)).fetchall()

    def alerts(self, station_id: str | None = None, limit: int = 50) -> list[dict]:
        q, args = "SELECT * FROM alerts", []
        if station_id:
            q += " WHERE station_id=?"
            args.append(station_id)
        q += " ORDER BY sent_at DESC LIMIT ?"
        return [dict(r) for r in self.conn.execute(q, args + [limit]).fetchall()]

    def pump_events(self, station_id: str, since_ts: float) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM pump_commands WHERE station_id=? AND issued_at>=? ORDER BY issued_at",
            (station_id, since_ts)).fetchall()]

    def latest_ts(self) -> float | None:
        return self.conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]


def _to_reading(row) -> Reading:
    return Reading(ts=row["ts"], soil_raw=json.loads(row["soil_raw"]), air_temp_c=row["air_temp_c"],
                   humidity=row["humidity"], pressure_hpa=row["pressure_hpa"], battery_v=row["battery_v"])
