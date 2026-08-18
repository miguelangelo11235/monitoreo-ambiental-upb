import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, OperationFailure, ServerSelectionTimeoutError

from models.measurement import Measurement
from storage.base import BaseStorage

logger = logging.getLogger("storage.mongodb")


class MongoDBStorage(BaseStorage):
    """Gestor de almacenamiento de mediciones en MongoDB (Atlas o Local)."""

    def __init__(
        self,
        uri: Optional[str] = None,
        db_name: str = "air_quality",
        collection_name: str = "raw_measurements"
    ):
        self.uri = uri
        self.db_name = db_name
        self.collection_name = collection_name
        self._client: Optional[MongoClient] = None
        self._collection: Optional[Collection] = None

    @staticmethod
    def validate_connection(uri: str, timeout_ms: int = 3000) -> bool:
        """Prueba rápida de conexión a la URI indicada de MongoDB."""
        if not uri:
            return False
        try:
            temp_client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
            temp_client.admin.command("ping")
            temp_client.close()
            return True
        except Exception as e:
            logger.error("Error al validar conexión con MongoDB (%s): %s", uri, e)
            return False

    def _get_collection(self) -> Optional[Collection]:
        """Obtiene la colección MongoDB, conectándose si es necesario."""
        if self._collection is not None:
            return self._collection

        if not self.uri:
            logger.warning("MongoDBStorage no tiene configurada una URI válida.")
            return None

        try:
            self._client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
            self._client.admin.command("ping")
            db = self._client[self.db_name]
            self._collection = db[self.collection_name]
            logger.info("Conectado exitosamente a MongoDB [%s / %s]", self.db_name, self.collection_name)
            return self._collection
        except (ServerSelectionTimeoutError, ConnectionFailure) as e:
            logger.error("No se pudo conectar a MongoDB (%s): %s", self.uri, e)
            self._client = None
            self._collection = None
            return None

    def _write_sync(self, measurement: Measurement) -> bool:
        """Invocación síncrona de inserción en MongoDB."""
        coll = self._get_collection()
        if coll is None:
            return False

        doc = {
            "timestamp": measurement.timestamp,
            "device_id": measurement.sensor_id,
            "metrics": measurement.metrics,
            "quality": measurement.quality,
            "location": measurement.location
        }

        try:
            coll.insert_one(doc)
            logger.info("✓ Registro almacenado exitosamente en MongoDB (BD: '%s', Colección: '%s', Sensor: '%s')", self.db_name, self.collection_name, measurement.sensor_id)
            print(f"✓ Registro almacenado exitosamente en MongoDB [BD: '{self.db_name}' | Colección: '{self.collection_name}' | Sensor: '{measurement.sensor_id}']")
            return True
        except OperationFailure as exc:
            logger.error("Error en operación de inserción en MongoDB: %s", exc)
            self.close()
            return False


    async def write(self, measurement: Measurement) -> None:
        """Escribe una medición en MongoDB de manera asíncrona."""
        if not self.uri:
            return
        success = await asyncio.to_thread(self._write_sync, measurement)
        if not success:
            logger.warning("No se pudo escribir la medición de '%s' en MongoDB", measurement.sensor_id)

    def _read_since_sync(self, timestamp: datetime) -> List[Measurement]:
        coll = self._get_collection()
        if coll is None:
            return []
        try:
            cursor = coll.find({"timestamp": {"$gte": timestamp}}).sort("timestamp", 1)
            results = []
            for doc in cursor:
                ts = doc.get("timestamp")
                if isinstance(ts, datetime) and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                m = Measurement(
                    sensor_id=doc.get("device_id", "unknown"),
                    timestamp=ts or datetime.now(timezone.utc),
                    location=doc.get("location", ""),
                    metrics=doc.get("metrics", {}),
                    quality=doc.get("quality", "ok")
                )
                results.append(m)
            return results
        except Exception as e:
            logger.error("Error leyendo mediciones de MongoDB: %s", e)
            return []

    async def read_since(self, timestamp: datetime) -> List[Measurement]:
        if not self.uri:
            return []
        return await asyncio.to_thread(self._read_since_sync, timestamp)

    def _delete_older_than_sync(self, days: int) -> None:
        coll = self._get_collection()
        if coll is None:
            return
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            res = coll.delete_many({"timestamp": {"$lt": cutoff}})
            logger.info("Eliminados %d documentos antiguos (>%d días) de MongoDB", res.deleted_count, days)
        except Exception as e:
            logger.error("Error al eliminar documentos antiguos de MongoDB: %s", e)

    async def delete_older_than(self, days: int) -> None:
        if not self.uri:
            return
        await asyncio.to_thread(self._delete_older_than_sync, days)

    async def flush(self) -> None:
        """En MongoDB la inserción es directa; flush no requiere acción adicional."""
        pass

    def close(self) -> None:
        """Cierra el cliente de MongoDB."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._collection = None
            logger.info("Conexión a MongoDB cerrada.")
