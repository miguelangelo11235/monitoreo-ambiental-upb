import sys
import subprocess
import socket
import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("services.network")


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class NetworkService:

    """Servicio de diagnóstico de conectividad, ping y pruebas de red."""

    @staticmethod
    async def ping_icmp(ip: str, count: int = 2, timeout_sec: float = 3.0) -> bool:
        """Realiza un ping ICMP nativo del SO hacia la dirección IP dada."""
        if not ip or ip == "127.0.0.1":
            return True
        param = "-n" if sys.platform.lower().startswith("win") else "-c"
        command = ["ping", param, str(count), ip]
        try:
            def _exec_ping():
                res = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_sec)
                return res.returncode == 0
            return await asyncio.to_thread(_exec_ping)
        except Exception as e:
            logger.debug(f"Error en ping ICMP a {ip}: {e}")
            return False

    @staticmethod
    async def ping(ip: str, timeout: float = 2.0) -> bool:
        """Intenta ping ICMP primero y luego pruebas TCP en puertos 80, 8002 y 1883."""
        if await NetworkService.ping_icmp(ip, count=1, timeout_sec=timeout):
            return True
        for port in [80, 8002, 1883]:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=timeout
                )
                writer.close()
                await writer.wait_closed()
                return True
            except Exception:
                continue
        return False

    @staticmethod
    async def test_http_endpoint(target: str, timeout: float = 5.0) -> bool:
        """Probar endpoint HTTP de AirLink probando en puerto 80 y puerto 8002."""
        if not target.startswith("http://") and not target.startswith("https://"):
            urls = [
                f"http://{target}/v1/current_conditions",
                f"http://{target}:8002/v1/current_conditions"
            ]
        else:
            urls = [target]
            # Si incluye puerto 8002, agregar versión puerto 80
            if ":8002" in target:
                urls.append(target.replace(":8002", ""))

        try:
            import aiohttp
            client_timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                for url in urls:
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                return True
                    except Exception:
                        continue
            return False
        except ImportError:
            logger.debug("aiohttp no está instalado.")
            return False

    @staticmethod
    async def discover_airlink_ip(api_key: str, api_secret: str) -> Optional[str]:
        """Descubre automáticamente la IP local de un AirLink registrado en la nube WeatherLink API v2."""
        if not api_key or not api_secret:
            return None
        try:
            import aiohttp
            url = "https://api.weatherlink.com/v2/current_conditions"
            headers = {"X-Api-Secret": api_secret}
            params = {"api-key": api_key}
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        json_data = await resp.json()
                        for sensor in json_data.get("sensors", []):
                            for sample in sensor.get("data", []):
                                ip = sample.get("ip_v4_address")
                                if ip:
                                    logger.info(f"IP local descubierta desde WeatherLink Cloud: {ip}")
                                    return ip
        except Exception as e:
            logger.error(f"Error al autodescubrir IP desde la nube: {e}")
        return None

    @staticmethod
    async def test_mqtt_connection(broker: str, port: int = 1883, timeout: float = 3.0) -> bool:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(broker, port), timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    @staticmethod
    async def check_internet_connectivity(timeout: float = 3.0) -> bool:
        return await NetworkService.test_http_endpoint("https://www.google.com", timeout=timeout)

