import socket
import asyncio
import logging

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
    """Servicio de diagnóstico de conectividad y pruebas de red."""

    @staticmethod
    async def ping(ip: str, timeout: float = 2.0) -> bool:
        """Intenta realizar una conexión TCP de prueba al puerto 80 o 8002 de la IP dada."""
        for port in [8002, 80, 1883]:
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
    async def test_http_endpoint(url: str, timeout: float = 5.0) -> bool:
        try:
            import aiohttp
            client_timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url) as resp:
                    return resp.status < 500
        except ImportError:
            logger.debug("aiohttp no está instalado. Prueba HTTP simulada.")
            return False
        except Exception:
            return False

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
