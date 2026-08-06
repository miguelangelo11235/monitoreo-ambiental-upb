import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from models.sensor import SensorConfig
from models.measurement import Measurement
from adapters.base_sensor import BaseSensorAdapter

logger = logging.getLogger("adapters.mqtt")


def parse_mqtt_payload(json_payload: str) -> Dict[str, Any]:
    """Parsea el payload JSON de un mensaje MQTT."""
    try:
        data = json.loads(json_payload)
        if isinstance(data, dict):
            return data
        return {"value": data}
    except Exception as e:
        logger.error(f"Error parseando JSON de MQTT: {e}")
        return {}


class MQTTClient:
    """Cliente wrapper para suscripción simple a MQTT."""

    def __init__(self, broker_ip: str, port: int = 1883):
        self.broker_ip = broker_ip
        self.port = port

    async def subscribe_once(self, topic: str, timeout: float = 5.0) -> Optional[str]:
        """Se suscribe a un tópico y espera por una sola publicación."""
        try:
            import aiomqtt
            async with aiomqtt.Client(hostname=self.broker_ip, port=self.port) as client:
                await client.subscribe(topic)
                async with client.messages() as messages:
                    async with asyncio.timeout(timeout):
                        async for message in messages:
                            return message.payload.decode("utf-8")
        except ImportError:
            logger.warning("aiomqtt no está instalado. Utilizando cliente simulado.")
            await asyncio.sleep(0.5)
            return None
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Timeout o error esperando mensaje MQTT en {topic}: {e}")
            return None


class MQTTSensorAdapter(BaseSensorAdapter):
    """Adaptador para sensores personalizados vía protocolo MQTT (ESP32, Pico W)."""

    def __init__(self, config: SensorConfig):
        super().__init__(config)
        broker = config.broker or config.ip or "127.0.0.1"
        self.mqtt_client = MQTTClient(broker_ip=broker)

    async def subscribe_and_wait(self, topic: str, timeout: float = 5.0) -> Dict[str, Any]:
        payload = await self.mqtt_client.subscribe_once(topic, timeout=timeout)
        if payload:
            return parse_mqtt_payload(payload)
        return {}

    async def read(self) -> Measurement:
        timestamp = datetime.now()
        topic = self.config.topic or f"sensors/{self.config.id}"
        timeout = float(self.config.timeout_seconds)

        metrics = await self.subscribe_and_wait(topic, timeout=timeout)

        if metrics:
            return Measurement(
                sensor_id=self.config.id,
                timestamp=timestamp,
                location=self.config.location,
                metrics=metrics,
                quality="ok"
            )
        else:
            return Measurement(
                sensor_id=self.config.id,
                timestamp=timestamp,
                location=self.config.location,
                metrics={},
                quality="sensor_timeout"
            )
