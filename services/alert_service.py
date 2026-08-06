import logging
from datetime import datetime
from typing import Optional, Dict, Any
from storage.sqlite_buffer import SQLiteBuffer

logger = logging.getLogger("services.alert")


def format_alert_message(sensor_id: str, error: str, timestamp: datetime) -> str:
    return f"[{timestamp.isoformat()}] Sensor '{sensor_id}' presentó fallo: {error}"


class AlertService:
    """Servicio no bloqueante para gestionar alertas y registrar eventos en la base de datos."""

    def __init__(self, sqlite_buffer: Optional[SQLiteBuffer] = None):
        self.sqlite_buffer = sqlite_buffer or SQLiteBuffer()

    def send_to_stdout(self, message: str) -> None:
        print(f"\n⚠️  ALERT: {message}\n")

    def send_to_email(self, message: str) -> None:
        # Stub para correo electrónico
        logger.debug(f"[Email Stub] Enviando email: {message}")

    async def write_event_to_db(self, event_type: str, sensor_id: Optional[str], message: str) -> None:
        try:
            await self.sqlite_buffer.write_event(event_type, sensor_id, message)
        except Exception as e:
            logger.error(f"Error escribiendo evento de alerta en DB: {e}")

    async def notify_sensor_failure(self, sensor_id: str, error: str) -> None:
        now = datetime.now()
        msg = format_alert_message(sensor_id, error, now)
        logger.warning(msg)
        self.send_to_stdout(msg)
        await self.write_event_to_db("sensor_alert", sensor_id, error)

    async def notify_network_issue(self, issue: str) -> None:
        now = datetime.now()
        msg = f"[{now.isoformat()}] Problema de Red: {issue}"
        logger.warning(msg)
        await self.write_event_to_db("network_error", None, issue)

    async def notify_db_error(self, error: str) -> None:
        now = datetime.now()
        msg = f"[{now.isoformat()}] Error de Base de Datos: {error}"
        logger.error(msg)
        await self.write_event_to_db("db_error", None, error)
