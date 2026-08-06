import logging
from datetime import datetime
from typing import List, Optional

from models.measurement import Measurement
from storage.base import BaseStorage
from core.config import settings

logger = logging.getLogger("storage.influxdb")


class InfluxDBStorage(BaseStorage):
    """Stub / Implementación inicial de InfluxDB para fase 2 de nube."""

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        org: Optional[str] = None,
        bucket: Optional[str] = None
    ):
        self.url = url or settings.influxdb_url
        self.token = token or settings.influxdb_token
        self.org = org or settings.influxdb_org
        self.bucket = bucket or settings.influxdb_bucket
        self.client = None

    async def connect(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str
    ) -> bool:
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        logger.info(f"Configurada conexión InfluxDB a {url}")
        return True

    async def write(self, measurement: Measurement) -> None:
        if not self.url or not self.token:
            logger.debug("InfluxDB no configurado. Omitiendo escritura.")
            return
        logger.info(f"[Stub InfluxDB] Escribiendo medición de {measurement.sensor_id}")

    async def read_since(self, timestamp: datetime) -> List[Measurement]:
        logger.info("[Stub InfluxDB] Consulta read_since omitida")
        return []

    async def query(self, sensor_id: str, start: datetime, end: datetime) -> List[Measurement]:
        logger.info(f"[Stub InfluxDB] Consulta rango omitida para {sensor_id}")
        return []

    async def delete_older_than(self, days: int) -> None:
        pass

    async def flush(self) -> None:
        pass
