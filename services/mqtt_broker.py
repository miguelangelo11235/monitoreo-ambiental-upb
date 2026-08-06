import asyncio
import subprocess
import logging
from typing import Optional
from core.config import settings
from services.network_service import NetworkService

logger = logging.getLogger("services.mqtt_broker")


def _spawn_mosquitto_process() -> Optional[subprocess.Popen]:
    try:
        proc = subprocess.Popen(["mosquitto", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc
    except FileNotFoundError:
        logger.warning("Mosquitto no está instalado o no se encuentra en el PATH.")
        return None
    except Exception as e:
        logger.error(f"Error lanzando Mosquitto: {e}")
        return None


class MQTTBrokerManager:
    """Manejo y monitoreo de salud del broker Mosquitto en la Raspberry Pi / host local."""

    def __init__(self, host: str = None, port: int = None):
        self.host = host or settings.mqtt_broker
        self.port = port or settings.mqtt_port
        self.process = None

    async def is_running(self) -> bool:
        return await NetworkService.test_mqtt_connection(self.host, self.port)

    async def healthcheck(self) -> bool:
        running = await self.is_running()
        if not running:
            logger.warning(f"Broker MQTT en {self.host}:{self.port} no responde.")
        return running

    async def start(self) -> bool:
        if await self.is_running():
            logger.info(f"Broker MQTT ya está corriendo en {self.host}:{self.port}")
            return True

        logger.info("Intentando iniciar servicio Mosquitto...")
        self.process = _spawn_mosquitto_process()
        await asyncio.sleep(2)

        if await self.is_running():
            logger.info("Broker Mosquitto iniciado exitosamente.")
            return True
        else:
            logger.warning("No se pudo iniciar el Broker Mosquitto localmente.")
            return False

    async def restart(self) -> bool:
        if self.process:
            self.process.terminate()
            self.process = None
        return await self.start()
