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
    def validate_connection(uri: str, timeout_ms: int = 5000) -> bool:
        """Prueba rápida de conexión a la URI indicada de MongoDB."""
        success, _, _ = MongoDBStorage.validate_connection_detailed(uri, timeout_ms=timeout_ms)
        return success

    @staticmethod
    def validate_connection_detailed(uri: str, timeout_ms: int = 5000) -> tuple[bool, str, str]:
        """
        Valida la conexión a MongoDB y retorna (éxito, resumen_error, diagnostico_detallado).
        """
        if not uri:
            return False, "URI no configurada", "No se ha proporcionado una URI de conexión a MongoDB."

        try:
            temp_client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms, connectTimeoutMS=timeout_ms)
            temp_client.admin.command("ping")
            temp_client.close()
            return True, "Conexión Exitosa", "✓ Conexión establecida correctamente con el servidor MongoDB."
        except Exception as e:
            err_msg = str(e)
            logger.error("Error al validar conexión con MongoDB (%s): %s", uri, err_msg)
            
            diag_lines = []
            err_lower = err_msg.lower()

            if "resolution lifetime expired" in err_lower or "lifetime expired" in err_lower or "dns" in err_lower or "srv" in err_lower or "servname" in err_lower:
                summary = "Error de Resolución DNS SRV en Raspberry Pi"
                diag_lines.append("❌ DETECTADO: El servidor DNS de tu red o Raspberry Pi no puede resolver los registros DNS SRV (mongodb+srv://).")
                diag_lines.append("   Error exacto: " + err_msg.split('\n')[0])
                diag_lines.append("\n💡 ¿POR QUÉ SUCEDE EN LA RASPBERRY PI Y NO EN LA PC?")
                diag_lines.append("   MongoDB Compass en tu PC utiliza resolvers DNS del sistema operativo o plantillas con caché.")
                diag_lines.append("   En Linux/Raspberry Pi, 'dnspython' consulta directamente a tu router/DNS local, el cual")
                diag_lines.append("   a menudo bloquea o no responde a tiempo a las consultas de registros DNS TXT/SRV de MongoDB Atlas.")
                diag_lines.append("\n🔧 SOLUCIONES EN LA RASPBERRY PI:")
                diag_lines.append("   1. Cambiar los servidores DNS de la Raspberry Pi a Google (8.8.8.8) o Cloudflare (1.1.1.1):")
                diag_lines.append("      En la consola de la Raspberry Pi ejecuta:")
                diag_lines.append("        sudo nano /etc/resolv.conf")
                diag_lines.append("      Y agrega como primera línea:")
                diag_lines.append("        nameserver 8.8.8.8")
                diag_lines.append("   2. Asegurar que 'dnspython' y 'pymongo' estén actualizados en el entorno virtual:")
                diag_lines.append("        pip install --upgrade dnspython pymongo")
                diag_lines.append("   3. Usar URI directa (formato mongodb:// con nodos o IP) si estás en una red muy restringida.")

            elif "bad auth" in err_lower or "authentication failed" in err_lower or "code 18" in err_lower or "operationfailure" in err_lower:
                summary = "Error de Autenticación (Credenciales Incorrectas)"
                diag_lines.append("❌ DETECTADO: Usuario o contraseña rechazados por el cluster de MongoDB Atlas.")
                diag_lines.append("   Error exacto: " + err_msg.split('\n')[0])
                diag_lines.append("\n💡 RECOMENDACIONES:")
                diag_lines.append("   • Verifica las credenciales en MongoDB Atlas (Database Access).")
                diag_lines.append("   • Si la contraseña o usuario contienen caracteres especiales (como @, #, $, %, ?, &),")
                diag_lines.append("     se requiere URL Encoding. (La opción 1 del menú aplica auto-encoding automáticamente).")

            elif "serverselectiontimeout" in err_lower or "timed out" in err_lower or "connection refused" in err_lower:
                summary = "Tiempo de Espera Agotado (Timeout de Red / IP Bloqueada)"
                diag_lines.append("❌ DETECTADO: No se recibió respuesta de los nodos de MongoDB.")
                diag_lines.append("   Error exacto: " + err_msg.split('\n')[0])
                diag_lines.append("\n💡 RECOMENDACIONES:")
                diag_lines.append("   • Asegúrate de agregar la IP de tu Raspberry Pi en MongoDB Atlas -> Network Access.")
                diag_lines.append("   • Para pruebas rápidas, puedes agregar la IP 0.0.0.0/0 (Permitir acceso desde cualquier lugar).")
                diag_lines.append("   • Verifica que la Raspberry Pi tenga acceso a Internet en el puerto 27017.")

            elif "ssl" in err_lower or "certificate" in err_lower or "tls" in err_lower:
                summary = "Error de Certificado SSL/TLS"
                diag_lines.append("❌ DETECTADO: Falló la verificación de certificado de seguridad SSL/TLS.")
                diag_lines.append("   Error exacto: " + err_msg.split('\n')[0])
                diag_lines.append("\n💡 RECOMENDACIONES:")
                diag_lines.append("   • Verifica que la fecha y hora de la Raspberry Pi estén sincronizadas ('date').")
                diag_lines.append("   • Ejecuta: 'sudo apt update && sudo apt install -y ca-certificates'")

            else:
                summary = "Error de Conexión a MongoDB"
                diag_lines.append("❌ DETECTADO: Ocurrió un error general al intentar conectar.")
                diag_lines.append("   Error exacto: " + err_msg)

            return False, summary, "\n".join(diag_lines)

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
