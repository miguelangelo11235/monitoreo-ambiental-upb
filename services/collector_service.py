import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from services.sensor_manager import SensorManager
from services.alert_service import AlertService
from storage.sqlite_buffer import SQLiteBuffer
from storage.csv_storage import CSVStorage
from storage.influxdb_storage import InfluxDBStorage

logger = logging.getLogger("services.collector")


def _should_sync(dt: Optional[datetime] = None) -> bool:
    """Verifica si el minuto actual corresponde a los intervalos de sincronización (:00, :15, :30, :45)."""
    now = dt or datetime.now()
    return now.minute in [0, 15, 30, 45]


class CollectorService:
    """Orquestador principal del ciclo de recolección y sincronización de datos."""

    def __init__(
        self,
        sensor_manager: Optional[SensorManager] = None,
        sqlite_buffer: Optional[SQLiteBuffer] = None,
        csv_storage: Optional[CSVStorage] = None,
        influx_storage: Optional[InfluxDBStorage] = None,
        alert_service: Optional[AlertService] = None
    ):
        self.sensor_manager = sensor_manager or SensorManager()
        self.sqlite_buffer = sqlite_buffer or SQLiteBuffer()
        self.csv_storage = csv_storage or CSVStorage()
        self.influx_storage = influx_storage or InfluxDBStorage()
        self.alert_service = alert_service or AlertService(self.sqlite_buffer)

        self._running = False
        self._collect_task: Optional[asyncio.Task] = None
        self._sync_task: Optional[asyncio.Task] = None
        self.last_collect_time: Optional[datetime] = None
        self.last_sync_time: Optional[datetime] = None
        self.recent_measurements: Dict[str, Any] = {}

    async def _read_single_sensor(self, adapter) -> None:
        sensor_id = adapter.config.id
        try:
            measurement = await adapter.read()
            self.recent_measurements[sensor_id] = measurement

            # Guardar en SQLite Buffer
            await self.sqlite_buffer.write(measurement)

            if measurement.quality != "ok":
                await self.alert_service.notify_sensor_failure(
                    sensor_id, f"Calidad de lectura: {measurement.quality}"
                )
            else:
                logger.info(f"{sensor_id}: lectura exitosa ({len(measurement.metrics)} métricas)")
        except Exception as e:
            logger.error(f"Excepción no capturada al leer sensor {sensor_id}: {e}")
            await self.alert_service.notify_sensor_failure(sensor_id, str(e))

    async def collect_loop(self) -> None:
        """Loop de lectura ejecutado cada 60 segundos."""
        logger.info("Iniciando bucle de recolección de sensores (cada 60s)...")
        while self._running:
            start_time = datetime.now()
            self.last_collect_time = start_time

            adapters = self.sensor_manager.get_all_adapters()
            if adapters:
                tasks = [self._read_single_sensor(adapter) for adapter in adapters]
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                logger.debug("No hay sensores activos para recolectar datos.")

            elapsed = (datetime.now() - start_time).total_seconds()
            sleep_time = max(1.0, 60.0 - elapsed)
            
            # Dormir en pequeñas iteraciones para permitir cancelación rápida
            slept = 0.0
            while self._running and slept < sleep_time:
                await asyncio.sleep(0.5)
                slept += 0.5

    async def sync_loop(self) -> None:
        """Loop de sincronización ejecutado periódicamente (cada 15 minutos en :00, :15, :30, :45)."""
        logger.info("Iniciando bucle de sincronización (intervalos de 15m)...")
        last_synced_minute = -1
        while self._running:
            now = datetime.now()
            if _should_sync(now) and now.minute != last_synced_minute:
                last_synced_minute = now.minute
                self.last_sync_time = now
                logger.info(f"Sincronizando buffer local SQLite -> CSV a las {now.strftime('%H:%M:%S')}...")
                try:
                    count = await self.sqlite_buffer.flush_to_csv(self.csv_storage)
                    logger.info(f"Sincronización completada: {count} registros transferidos a CSV.")

                    if self.influx_storage and self.influx_storage.url:
                        unsynced_measurements = await self.sqlite_buffer.read_since(now)
                        for m in unsynced_measurements:
                            await self.influx_storage.write(m)
                except Exception as e:
                    logger.error(f"Error en bucle de sincronización: {e}")
                    await self.alert_service.notify_db_error(str(e))

            # Esperar 5s verificando _running para respuesta rápida
            slept = 0.0
            while self._running and slept < 5.0:
                await asyncio.sleep(0.5)
                slept += 0.5

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._collect_task = asyncio.create_task(self.collect_loop())
        self._sync_task = asyncio.create_task(self.sync_loop())
        logger.info("CollectorService iniciado.")

    async def stop(self) -> None:
        """Detiene los bucles de recolección en segundo plano de forma limpia sin cerrar storages."""
        if not self._running:
            return
        logger.info("Pausando bucles de recolección...")
        self._running = False
        if self._collect_task:
            self._collect_task.cancel()
            self._collect_task = None
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
        logger.info("Recolección pausada exitosamente.")

    async def shutdown(self) -> None:
        logger.info("Deteniendo CollectorService y cerrando persistencia...")
        await self.stop()
        try:
            logger.info("Realizando vaciado final del buffer SQLite a CSV...")
            await self.sqlite_buffer.flush_to_csv(self.csv_storage)
        except Exception as e:
            logger.error(f"Error durante el flush final: {e}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "last_collect_time": self.last_collect_time.isoformat() if self.last_collect_time else None,
            "last_sync_time": self.last_sync_time.isoformat() if self.last_sync_time else None,
            "total_sensors": len(self.sensor_manager.list_sensors()),
            "active_adapters": len(self.sensor_manager.get_all_adapters()),
            "recent_measurements": {
                sid: m.model_dump() for sid, m in self.recent_measurements.items()
            }
        }
