import logging
from datetime import datetime
from typing import Dict, Any, Optional
from core.config import settings

logger = logging.getLogger("adapters.fallback_handler")


def log_fallback_attempt(sensor_id: str, reason: str):
    logger.warning(f"Intento de fallback para sensor {sensor_id}: {reason}")


class FallbackHandler:
    """Maneja estrategias de resiliencia y fallback para sensores."""

    def __init__(self):
        self.davis_api_key = settings.davis_api_key
        self.davis_api_secret = settings.davis_api_secret

    async def fetch_from_davis_api(self, station_id: Optional[str] = None) -> Dict[str, Any]:
        """Consulta la API de Davis Cloud como solución de respaldo."""
        if not self.davis_api_key or not self.davis_api_secret:
            logger.warning("Credenciales de Davis API no configuradas para fallback")
            return {}

        url = "https://api.weatherlink.com/v2/current"
        params = {
            "api-key": self.davis_api_key,
            "station-id": station_id or ""
        }
        headers = {"X-Api-Secret": self.davis_api_secret}

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    else:
                        logger.error(f"Fallback Davis API retornó status {response.status}")
                        return {}
        except ImportError:
            logger.warning("aiohttp no está instalado.")
            return {}
        except Exception as e:
            logger.error(f"Error al realizar fallback a Davis API: {e}")
            return {}

    async def try_fallback(self, sensor_id: str, error_count: int) -> Dict[str, Any]:
        """Intenta obtener datos por vías alternativas si las fallas superan un umbral."""
        log_fallback_attempt(sensor_id, f"Fallas consecutivas: {error_count}")
        return await self.fetch_from_davis_api(station_id=sensor_id)
