import sys
import asyncio
import signal
import logging

from core.config import settings
from services.log_service import setup_logger
from services.sensor_manager import SensorManager
from services.mqtt_broker import MQTTBrokerManager
from services.collector_service import CollectorService
from services.alert_service import AlertService
from storage.sqlite_buffer import SQLiteBuffer
from storage.csv_storage import CSVStorage
from storage.influxdb_storage import InfluxDBStorage
from storage.mongodb_storage import MongoDBStorage
from ui.cli import CLIMenu

logger = setup_logger("main")


async def main():
    logger.info("=== Iniciando Sistema de Monitoreo Ambiental Campus ===")

    # 1. Cargar gestor de sensores y storages
    sensor_manager = SensorManager(settings.sensors_config_path)
    sqlite_buffer = SQLiteBuffer(settings.sqlite_path)
    csv_storage = CSVStorage(settings.csv_path)
    influx_storage = InfluxDBStorage(
        url=settings.influxdb_url,
        token=settings.influxdb_token,
        org=settings.influxdb_org,
        bucket=settings.influxdb_bucket
    )
    mongo_storage = MongoDBStorage(
        uri=settings.mongo_uri,
        db_name=settings.mongo_db,
        collection_name=settings.mongo_collection
    )

    # 2. Iniciar Broker MQTT
    mqtt_manager = MQTTBrokerManager(settings.mqtt_broker, settings.mqtt_port)
    await mqtt_manager.start()

    # 3. Servicios
    alert_service = AlertService(sqlite_buffer)
    collector = CollectorService(
        sensor_manager=sensor_manager,
        sqlite_buffer=sqlite_buffer,
        csv_storage=csv_storage,
        influx_storage=influx_storage,
        mongo_storage=mongo_storage,
        alert_service=alert_service,
        sync_interval_min=settings.mongo_save_interval_min,
        sync_mode=getattr(settings, "mongo_sync_mode", "closed")
    )

    # 4. Iniciar CLI Menu (El recolector se activa opcionalmente desde la Opción 1 del Menú)
    cli = CLIMenu(
        collector_service=collector,
        sensor_manager=sensor_manager,
        sqlite_buffer=sqlite_buffer,
        csv_storage=csv_storage,
        mongo_storage=mongo_storage
    )


    loop = asyncio.get_running_loop()

    def handle_signal():
        logger.info("Señal de parada recibida (SIGINT/SIGTERM).")
        asyncio.create_task(shutdown(collector))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    try:
        await cli.show_main_menu()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Interrupción de teclado capturada en main.")
    finally:
        await collector.shutdown()
        logger.info("=== Sistema finalizado correctamente ===")


async def shutdown(collector: CollectorService):
    await collector.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
