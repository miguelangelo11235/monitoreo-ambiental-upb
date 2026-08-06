import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from models.measurement import Measurement
from storage.base import BaseStorage
from storage.csv_storage import CSVStorage
from core.config import settings

logger = logging.getLogger("storage.sqlite")


class SQLiteBuffer(BaseStorage):
    """Buffer local en SQLite para alta resiliencia frente a caídas de red o energía."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.sqlite_path
        self._create_tables()

    def _get_connection(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_tables(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    sensor_id TEXT NOT NULL,
                    location TEXT,
                    metrics TEXT,
                    quality TEXT NOT NULL,
                    synced INTEGER DEFAULT 0
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    sensor_id TEXT,
                    message TEXT NOT NULL
                )
            """)
            conn.commit()

    async def write(self, measurement: Measurement) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO measurements (timestamp, sensor_id, location, metrics, quality, synced)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (
                    measurement.timestamp.isoformat(),
                    measurement.sensor_id,
                    measurement.location,
                    json.dumps(measurement.metrics),
                    measurement.quality
                )
            )
            conn.commit()

    async def write_event(self, event_type: str, sensor_id: Optional[str], message: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO events (timestamp, event_type, sensor_id, message)
                VALUES (?, ?, ?, ?)
                """,
                (datetime.now().isoformat(), event_type, sensor_id, message)
            )
            conn.commit()

    async def read_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def read_since(self, timestamp: datetime) -> List[Measurement]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM measurements WHERE timestamp >= ? ORDER BY id ASC",
                (timestamp.isoformat(),)
            )
            rows = cursor.fetchall()
            measurements = []
            for row in rows:
                measurements.append(
                    Measurement(
                        sensor_id=row["sensor_id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        location=row["location"] or "",
                        metrics=json.loads(row["metrics"]) if row["metrics"] else {},
                        quality=row["quality"]
                    )
                )
            return measurements

    async def read_unsynced(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM measurements WHERE synced = 0 ORDER BY id ASC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def read_all(self) -> List[Measurement]:
        return await self.read_since(datetime.min)

    async def mark_as_synced(self, record_ids: List[int]) -> None:
        if not record_ids:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                "UPDATE measurements SET synced = 1 WHERE id = ?",
                [(rid,) for rid in record_ids]
            )
            conn.commit()

    async def count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM measurements")
            return cursor.fetchone()[0]

    async def clear_synced(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM measurements WHERE synced = 1")
            conn.commit()

    async def clear(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM measurements")
            cursor.execute("DELETE FROM events")
            conn.commit()

    async def flush_to_csv(self, csv_storage: CSVStorage) -> int:
        """Transfiere los datos del buffer no sincronizados hacia el archivo CSV y los marca como sincronizados."""
        unsynced = await self.read_unsynced()
        if not unsynced:
            return 0

        synced_ids = []
        for row in unsynced:
            m = Measurement(
                sensor_id=row["sensor_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                location=row["location"] or "",
                metrics=json.loads(row["metrics"]) if row["metrics"] else {},
                quality=row["quality"]
            )
            await csv_storage.write(m)
            synced_ids.append(row["id"])

        await self.mark_as_synced(synced_ids)
        await self.clear_synced()
        return len(synced_ids)

    async def delete_older_than(self, days: int) -> None:
        cutoff = datetime.now().timestamp() - (days * 86400)
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM measurements WHERE timestamp < ?", (cutoff_iso,))
            cursor.execute("DELETE FROM events WHERE timestamp < ?", (cutoff_iso,))
            conn.commit()

    async def flush(self) -> None:
        pass
