import asyncio
import logging
from datetime import datetime
from typing import Dict, Any

from models.sensor import SensorConfig
from models.measurement import Measurement
from adapters.base_sensor import BaseSensorAdapter
from adapters.fallback_handler import FallbackHandler

logger = logging.getLogger("adapters.airlink")


def parse_airlink_response(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae y normaliza las métricas recibidas de la API de Davis AirLink."""
    metrics = {}
    try:
        data = json_data.get("data", json_data)
        conditions = data.get("conditions", [])
        if isinstance(conditions, list) and len(conditions) > 0:
            cond = conditions[0]
            if "temp" in cond:
                metrics["temperature"] = cond["temp"]
            if "hum" in cond:
                metrics["humidity"] = cond["hum"]
            if "dew_point" in cond:
                metrics["dew_point"] = cond["dew_point"]
            if "wet_bulb" in cond:
                metrics["wet_bulb"] = cond["wet_bulb"]
            if "heat_index" in cond:
                metrics["heat_index"] = cond["heat_index"]
            if "pm_1" in cond:
                metrics["pm_1"] = cond["pm_1"]
            if "pm_2p5" in cond:
                metrics["pm_2p5"] = cond["pm_2p5"]
            if "pm_10" in cond:
                metrics["pm_10"] = cond["pm_10"]
        else:
            for key in ["temp", "temperature", "hum", "humidity", "pressure"]:
                if key in data:
                    metrics[key] = data[key]
    except Exception as e:
        logger.error(f"Error parseando respuesta de AirLink: {e}")
    return metrics


class AirlinkAdapter(BaseSensorAdapter):
    """Adaptador para sensor Davis AirLink mediante API REST HTTP local."""

    def __init__(self, config: SensorConfig):
        super().__init__(config)
        self.fallback_handler = FallbackHandler()
        self.consecutive_errors = 0

    async def fetch_from_local_api(self) -> Dict[str, Any]:
        url = f"http://{self.config.ip}:8002/v1/current_conditions"
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        raise Exception(f"HTTP Status {response.status}")
        except ImportError:
            logger.warning("aiohttp no está instalado.")
            raise Exception("aiohttp no disponible")

    async def fallback_to_davis_api(self) -> Dict[str, Any]:
        return await self.fallback_handler.try_fallback(self.config.id, self.consecutive_errors)

    async def read(self) -> Measurement:
        timestamp = datetime.now()
        try:
            raw_data = await self.fetch_from_local_api()
            metrics = parse_airlink_response(raw_data)
            self.consecutive_errors = 0
            return Measurement(
                sensor_id=self.config.id,
                timestamp=timestamp,
                location=self.config.location,
                metrics=metrics,
                quality="ok"
            )
        except (asyncio.TimeoutError, Exception) as e:
            self.consecutive_errors += 1
            logger.warning(f"Error o timeout leyendo AirLink local ({self.config.id}): {e}")

            fallback_data = await self.fallback_to_davis_api()
            if fallback_data:
                metrics = parse_airlink_response(fallback_data)
                return Measurement(
                    sensor_id=self.config.id,
                    timestamp=timestamp,
                    location=self.config.location,
                    metrics=metrics,
                    quality="davis_fallback"
                )

            return Measurement(
                sensor_id=self.config.id,
                timestamp=timestamp,
                location=self.config.location,
                metrics={},
                quality="sensor_timeout"
            )
