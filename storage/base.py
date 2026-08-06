from abc import ABC, abstractmethod
from datetime import datetime
from typing import List
from models.measurement import Measurement


class BaseStorage(ABC):
    """Interfaz abstracta base para los servicios de almacenamiento."""

    @abstractmethod
    async def write(self, measurement: Measurement) -> None:
        """Escribe una medición en la persistencia."""
        pass

    @abstractmethod
    async def read_since(self, timestamp: datetime) -> List[Measurement]:
        """Obtiene todas las mediciones desde una fecha/hora especificada."""
        pass

    @abstractmethod
    async def delete_older_than(self, days: int) -> None:
        """Elimina mediciones más antiguas que N días."""
        pass

    @abstractmethod
    async def flush(self) -> None:
        """Fuerza la escritura o sincronización de búferes si aplica."""
        pass

