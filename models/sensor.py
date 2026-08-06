from typing import Optional
from pydantic import BaseModel, Field


class SensorConfig(BaseModel):
    id: str
    name: str
    type: str  # "airlink", "mqtt", "esp32"
    protocol: str = "http"  # "http", "mqtt"
    ip: str = "127.0.0.1"
    broker: Optional[str] = "127.0.0.1"
    topic: Optional[str] = None
    station_id: Optional[str] = None  # ID de estación en WeatherLink v2 API (entero o UUID)
    location: str = ""
    enabled: bool = True
    timeout_seconds: int = Field(default=5, ge=1)
