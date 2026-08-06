from datetime import datetime
from typing import Dict, Any
from pydantic import BaseModel, Field


class Measurement(BaseModel):
    sensor_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    location: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)
    quality: str = "ok"  # "ok", "sensor_timeout", "parsing_error", "davis_fallback"
    unit_system: str = "metric"
