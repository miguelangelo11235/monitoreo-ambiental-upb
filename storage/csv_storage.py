import os
import csv
import logging
from datetime import datetime
from typing import List, Optional, Any

from models.measurement import Measurement
from storage.base import BaseStorage
from core.config import settings

logger = logging.getLogger("storage.csv")


class CSVStorage(BaseStorage):
    """Almacenamiento permanente en archivo CSV (append-only)."""

    HEADERS = ["timestamp", "sensor_id", "location", "metric_name", "metric_value", "quality"]

    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = csv_path or settings.csv_path
        self._ensure_headers()

    def _ensure_headers(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.csv_path)), exist_ok=True)
        if not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0:
            with open(self.csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.HEADERS)

    async def write(self, measurement: Measurement) -> None:
        self._ensure_headers()
        rows = []
        iso_timestamp = measurement.timestamp.isoformat()
        
        if not measurement.metrics:
            rows.append([
                iso_timestamp,
                measurement.sensor_id,
                measurement.location,
                "none",
                "",
                measurement.quality
            ])
        else:
            for metric_name, metric_value in measurement.metrics.items():
                rows.append([
                    iso_timestamp,
                    measurement.sensor_id,
                    measurement.location,
                    metric_name,
                    str(metric_value),
                    measurement.quality
                ])

        with open(self.csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

    async def read_since(self, timestamp: datetime) -> List[Measurement]:
        if not os.path.exists(self.csv_path):
            return []

        measurements_map = {}
        with open(self.csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    row_time = datetime.fromisoformat(row["timestamp"])
                    if row_time >= timestamp:
                        key = (row["timestamp"], row["sensor_id"])
                        if key not in measurements_map:
                            measurements_map[key] = Measurement(
                                sensor_id=row["sensor_id"],
                                timestamp=row_time,
                                location=row["location"],
                                metrics={},
                                quality=row["quality"]
                            )
                        if row["metric_name"] != "none" and row["metric_value"] != "":
                            val_str = row["metric_value"]
                            try:
                                val = float(val_str) if "." in val_str else int(val_str)
                            except ValueError:
                                val = val_str
                            measurements_map[key].metrics[row["metric_name"]] = val
                except Exception as e:
                    logger.error(f"Error parseando fila de CSV: {e}")
        return list(measurements_map.values())

    async def export_range(self, start: datetime, end: datetime) -> Any:
        """Exporta mediciones en un rango de tiempo como un DataFrame de Pandas."""
        try:
            import pandas as pd
            if not os.path.exists(self.csv_path):
                return pd.DataFrame(columns=self.HEADERS)

            df = pd.read_csv(self.csv_path)
            if df.empty:
                return df
                
            df["timestamp_dt"] = pd.to_datetime(df["timestamp"])
            filtered_df = df[(df["timestamp_dt"] >= start) & (df["timestamp_dt"] <= end)]
            return filtered_df.drop(columns=["timestamp_dt"])
        except ImportError:
            logger.warning("Pandas no está instalado.")
            return []

    async def delete_older_than(self, days: int) -> None:
        if not os.path.exists(self.csv_path):
            return
            
        cutoff = datetime.now().timestamp() - (days * 86400)
        temp_path = self.csv_path + ".tmp"

        with open(self.csv_path, mode="r", encoding="utf-8") as fin, \
             open(temp_path, mode="w", newline="", encoding="utf-8") as fout:
            reader = csv.DictReader(fin)
            writer = csv.writer(fout)
            writer.writerow(self.HEADERS)
            for row in reader:
                try:
                    dt = datetime.fromisoformat(row["timestamp"])
                    if dt.timestamp() >= cutoff:
                        writer.writerow([row[h] for h in self.HEADERS])
                except Exception:
                    pass

        os.replace(temp_path, self.csv_path)

    async def flush(self) -> None:
        pass
