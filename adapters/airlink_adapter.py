import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from models.sensor import SensorConfig
from models.measurement import Measurement
from adapters.base_sensor import BaseSensorAdapter
from adapters.fallback_handler import FallbackHandler

logger = logging.getLogger("adapters.airlink")


def parse_airlink_response(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preserva la estructura completa de la API oficial de AirLink.
    Captura los metadatos raíz (did, name, ts) y todas las condiciones del sensor (medidas y calculadas).
    """
    metrics = {}
    try:
        data = json_data.get("data", json_data)
        if isinstance(data, dict):
            # Preservar metadatos raíz del sensor
            for root_key in ["did", "name", "ts"]:
                if root_key in data:
                    metrics[root_key] = data[root_key]

            conditions = data.get("conditions", [])
            cond = conditions[0] if (isinstance(conditions, list) and len(conditions) > 0) else data
            if isinstance(cond, dict):
                # Preservar todas las condiciones (mediciones y variables calculadas)
                for k, v in cond.items():
                    metrics[k] = v
        elif isinstance(json_data, dict):
            metrics = dict(json_data)
    except Exception as e:
        logger.error(f"Error parseando respuesta completa de AirLink: {e}")
    return metrics





class AirlinkAdapter(BaseSensorAdapter):
    """Adaptador para sensor Davis AirLink mediante API REST HTTP local o WeatherLink v2 API en nube."""

    def __init__(self, config: SensorConfig):
        super().__init__(config)
        self.fallback_handler = FallbackHandler()
        self.consecutive_errors = 0

    async def fetch_from_local_api(self) -> Dict[str, Any]:
        urls = [
            f"http://{self.config.ip}/v1/current_conditions",
            f"http://{self.config.ip}:8002/v1/current_conditions"
        ]
        last_error = None
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for url in urls:
                    try:
                        async with session.get(url) as response:
                            if response.status == 200:
                                return await response.json()
                            else:
                                last_error = Exception(f"HTTP Status {response.status} en {url}")
                    except Exception as e:
                        last_error = e
                        continue
            if last_error:
                raise last_error
            raise Exception("No se pudo conectar a AirLink local")
        except ImportError:
            logger.warning("aiohttp no está instalado.")
            raise Exception("aiohttp no disponible")


    async def fallback_to_davis_api(self) -> Dict[str, Any]:
        station_id = self.config.station_id or self.config.id
        return await self.fallback_handler.try_fallback(
            self.config.id, self.consecutive_errors, station_id=station_id
        )

    async def read(self) -> Measurement:
        now_dt = datetime.now()
        try:
            raw_data = await self.fetch_from_local_api()
            metrics = parse_airlink_response(raw_data)
            self.consecutive_errors = 0

            # Utilizar el timestamp 'ts' de la lectura del sensor si está disponible
            ts_val = metrics.get("ts")
            reading_dt = datetime.fromtimestamp(ts_val) if isinstance(ts_val, (int, float)) else now_dt

            return Measurement(
                sensor_id=self.config.id,
                timestamp=reading_dt,
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
                ts_val = metrics.get("ts")
                reading_dt = datetime.fromtimestamp(ts_val) if isinstance(ts_val, (int, float)) else now_dt
                return Measurement(
                    sensor_id=self.config.id,
                    timestamp=reading_dt,
                    location=self.config.location,
                    metrics=metrics,
                    quality="davis_fallback"
                )

            return Measurement(
                sensor_id=self.config.id,
                timestamp=now_dt,
                location=self.config.location,
                metrics={},
                quality="sensor_timeout"
            )

