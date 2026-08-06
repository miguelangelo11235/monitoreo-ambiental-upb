from abc import ABC, abstractmethod
from models.sensor import SensorConfig
from models.measurement import Measurement


class BaseSensorAdapter(ABC):
    """Interfaz abstracta base para todos los adaptadores de sensores."""

    def __init__(self, config: SensorConfig):
        self.config = config

    @abstractmethod
    async def read(self) -> Measurement:
        """Lee datos del sensor de forma asíncrona y retorna un objeto Measurement."""
        pass
