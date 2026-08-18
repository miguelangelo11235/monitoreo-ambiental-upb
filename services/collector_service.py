import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from services.sensor_manager import SensorManager
from services.alert_service import AlertService
from storage.sqlite_buffer import SQLiteBuffer
from storage.csv_storage import CSVStorage
from storage.influxdb_storage import InfluxDBStorage
from storage.mongodb_storage import MongoDBStorage

logger = logging.getLogger("services.collector")


def _should_sync(dt: Optional[datetime] = None, interval_min: int = 15) -> bool:
    """Verifica si el minuto actual es múltiplo del intervalo de guardado (por defecto cada 15m: :00, :15, :30, :45)."""
    now = dt or datetime.now()
    return (now.minute % interval_min) == 0

class CollectorService:
    """Orquestador principal del ciclo de recolección y sincronización de datos."""

    def __init__(
        self,
        sensor_manager: Optional[SensorManager] = None,
        sqlite_buffer: Optional[SQLiteBuffer] = None,
        csv_storage: Optional[CSVStorage] = None,
        influx_storage: Optional[InfluxDBStorage] = None,
        mongo_storage: Optional[MongoDBStorage] = None,
        alert_service: Optional[AlertService] = None,
        sync_interval_min: int = 15,
        collect_interval_min: int = 1
    ):
        self.sensor_manager = sensor_manager or SensorManager()
        self.sqlite_buffer = sqlite_buffer or SQLiteBuffer()
        self.csv_storage = csv_storage or CSVStorage()
        self.influx_storage = influx_storage or InfluxDBStorage()
        self.mongo_storage = mongo_storage or MongoDBStorage()
        self.alert_service = alert_service or AlertService(self.sqlite_buffer)
        self.sync_interval_min = sync_interval_min
        self.collect_interval_min = max(1, collect_interval_min)

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

            ts_str = measurement.timestamp.strftime("%Y-%m-%d %H:%M:%S")

            if measurement.quality not in ["ok", "davis_fallback"]:
                # Mostrar sin conexión en el instante de lectura de forma limpia sin alarmas excesivas
                logger.info(f"✗ Timestamp: {ts_str} | Sensor: {sensor_id} | [sin conexión]")
                print(f"✗ Timestamp: {ts_str} | Sensor: {sensor_id} | [sin conexión]")
            else:
                m = measurement.metrics
                raw_temp = m.get('temp')
                if isinstance(raw_temp, (int, float)):
                    temp_c_str = f"{round((raw_temp - 32) * 5 / 9, 1)}°C"
                else:
                    temp_c_str = f"{raw_temp}°C" if raw_temp is not None else "N/D"

                hum = f"{m.get('hum')}%" if m.get('hum') is not None else "N/D"
                pm1 = f"{m.get('pm_1_last')} ug/m3" if m.get('pm_1_last') is not None else "N/D"
                pm25 = f"{m.get('pm_2p5_last')} ug/m3" if m.get('pm_2p5_last') is not None else "N/D"
                pm10 = f"{m.get('pm_10_last')} ug/m3" if m.get('pm_10_last') is not None else "N/D"

                out_line = f"✓ Timestamp: {ts_str} | Sensor: {sensor_id} | Temp: {temp_c_str} | Hum: {hum} | PM1.0: {pm1} | PM2.5: {pm25} | PM10: {pm10}"
                logger.info(out_line)
                print(out_line)

        except Exception as e:
            ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"✗ Timestamp: {ts_str} | Sensor: {sensor_id} | [sin conexión]")
            print(f"✗ Timestamp: {ts_str} | Sensor: {sensor_id} | [sin conexión]")

    async def collect_loop(self) -> None:
        """Loop de recolección ejecutado con la frecuencia configurada en minutos."""
        logger.info(f"Iniciando bucle de recolección de sensores (cada {self.collect_interval_min}m)...")
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
            target_sec = self.collect_interval_min * 60.0
            sleep_time = max(1.0, target_sec - elapsed)
            
            # Dormir en pequeñas iteraciones para permitir cancelación rápida
            slept = 0.0
            while self._running and slept < sleep_time:
                await asyncio.sleep(0.5)
                slept += 0.5


    async def sync_loop(self) -> None:
        """Loop de sincronización ejecutado periódicamente (cada sync_interval_min minutos)."""
        logger.info(f"Iniciando bucle de sincronización (intervalos de {self.sync_interval_min}m)...")
        last_synced_minute = -1
        while self._running:
            now = datetime.now()
            if _should_sync(now, self.sync_interval_min) and now.minute != last_synced_minute:
                last_synced_minute = now.minute
                self.last_sync_time = now
                logger.info(f"Sincronizando a las {now.strftime('%H:%M:%S')}...")
                try:
                    count = await self.sqlite_buffer.flush_to_csv(self.csv_storage)
                    logger.info(f"Sincronización completada: {count} registros transferidos a CSV.")

                    if self.influx_storage and self.influx_storage.url:
                        unsynced_measurements = await self.sqlite_buffer.read_since(now)
                        for m in unsynced_measurements:
                            await self.influx_storage.write(m)

                    if self.mongo_storage and self.mongo_storage.uri:
                        logger.info(f"Enviando lecturas puntuales a MongoDB ({self.mongo_storage.db_name})...")
                        unsynced_measurements = await self.sqlite_buffer.read_since(now)
                        if unsynced_measurements:
                            for m in unsynced_measurements:
                                await self.mongo_storage.write(m)
                        elif self.recent_measurements:
                            for m in self.recent_measurements.values():
                                await self.mongo_storage.write(m)
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
            if self.mongo_storage:
                self.mongo_storage.close()
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
