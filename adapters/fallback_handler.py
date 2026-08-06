import logging
from typing import Dict, Any, List, Optional
from core.config import settings

logger = logging.getLogger("adapters.fallback_handler")


def log_fallback_attempt(sensor_id: str, reason: str):
    logger.warning(f"Intento de fallback para sensor {sensor_id}: {reason}")


class FallbackHandler:
    """Maneja las solicitudes HTTP a la API WeatherLink v2 (Davis Cloud) para obtención de estaciones y fallback."""

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key or settings.davis_api_key
        self.api_secret = api_secret or settings.davis_api_secret

    def _get_credentials(self, custom_key: Optional[str] = None, custom_secret: Optional[str] = None):
        key = custom_key or self.api_key or settings.davis_api_key
        secret = custom_secret or self.api_secret or settings.davis_api_secret
        return key, secret

    async def fetch_stations(
        self, api_key: Optional[str] = None, api_secret: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Paso 2 API v2: Consulta el endpoint /v2/stations para obtener la lista de estaciones y sus station_id."""
        key, secret = self._get_credentials(api_key, api_secret)
        if not key or not secret:
            logger.warning("WeatherLink v2 API Key o API Secret no configurados.")
            return []

        url = f"https://api.weatherlink.com/v2/stations?api-key={key}"
        headers = {"X-Api-Secret": secret}

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("stations", [])
                    else:
                        text = await response.text()
                        logger.error(f"Error /v2/stations ({response.status}): {text}")
                        return []
        except Exception as e:
            logger.error(f"Excepción al consultar WeatherLink /v2/stations: {e}")
            return []

    async def fetch_current_conditions(
        self, station_id: str, api_key: Optional[str] = None, api_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Paso 3 API v2: Consulta /v2/current/{station-id} para obtener mediciones actuales."""
        key, secret = self._get_credentials(api_key, api_secret)
        if not key or not secret or not station_id:
            logger.warning("Credenciales de Davis API o station_id faltantes.")
            return {}

        url = f"https://api.weatherlink.com/v2/current/{station_id}?api-key={key}"
        headers = {"X-Api-Secret": secret}

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        text = await response.text()
                        logger.error(f"Error /v2/current/{station_id} ({response.status}): {text}")
                        return {}
        except Exception as e:
            logger.error(f"Excepción al consultar WeatherLink /v2/current/{station_id}: {e}")
            return {}

    async def fetch_historic_conditions(
        self,
        station_id: str,
        start_timestamp: int,
        end_timestamp: int,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Paso 4 API v2: Consulta /v2/historic/{station-id} con timestamps en Unix."""
        key, secret = self._get_credentials(api_key, api_secret)
        if not key or not secret or not station_id:
            return {}

        url = (
            f"https://api.weatherlink.com/v2/historic/{station_id}"
            f"?api-key={key}&start-timestamp={start_timestamp}&end-timestamp={end_timestamp}"
        )
        headers = {"X-Api-Secret": secret}

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        text = await response.text()
                        logger.error(f"Error /v2/historic/{station_id} ({response.status}): {text}")
                        return {}
        except Exception as e:
            logger.error(f"Excepción al consultar WeatherLink /v2/historic: {e}")
            return {}

    async def try_fallback(self, sensor_id: str, error_count: int, station_id: Optional[str] = None) -> Dict[str, Any]:
        """Intenta fallback a WeatherLink Cloud API v2 si se conoce el station_id o la clave."""
        log_fallback_attempt(sensor_id, f"Fallas consecutivas: {error_count}")
        if station_id:
            return await self.fetch_current_conditions(station_id)
        return {}
