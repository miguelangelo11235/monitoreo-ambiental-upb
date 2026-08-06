import os
import json
import logging
from typing import List, Dict, Optional

from models.sensor import SensorConfig
from adapters.base_sensor import BaseSensorAdapter
from adapters.airlink_adapter import AirlinkAdapter
from adapters.mqtt_sensor_adapter import MQTTSensorAdapter
from core.config import settings

logger = logging.getLogger("services.sensor_manager")


def _validate_config(config: SensorConfig) -> bool:
    if not config.id or not config.name or not config.type:
        return False
    if config.type not in ["airlink", "mqtt", "esp32", "pico"]:
        return False
    return True


class SensorManager:
    """Gestor dinámico de sensores (patrón Factory) que permite agregar/remover sin reiniciar."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or settings.sensors_config_path
        self.sensors_config: Dict[str, SensorConfig] = {}
        self.adapters: Dict[str, BaseSensorAdapter] = {}
        self.load_from_config()

    def create_adapter(self, config: SensorConfig) -> BaseSensorAdapter:
        if config.type == "airlink":
            return AirlinkAdapter(config)
        elif config.type in ["mqtt", "esp32", "pico"]:
            return MQTTSensorAdapter(config)
        else:
            raise ValueError(f"Tipo de sensor desconocido: {config.type}")

    def load_from_config(self) -> List[SensorConfig]:
        if not os.path.exists(self.config_path):
            logger.warning(f"Archivo de configuración {self.config_path} no existe. Se utilizará lista vacía.")
            return []

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                sensors_raw = data.get("sensors", [])
                
                self.sensors_config.clear()
                self.adapters.clear()

                for raw_item in sensors_raw:
                    config = SensorConfig(**raw_item)
                    if _validate_config(config) and config.enabled:
                        self.sensors_config[config.id] = config
                        self.adapters[config.id] = self.create_adapter(config)

                logger.info(f"Cargados {len(self.adapters)} sensores activos desde {self.config_path}")
                return list(self.sensors_config.values())
        except Exception as e:
            logger.error(f"Error cargando archivo de configuración {self.config_path}: {e}")
            return []

    def save_config(self) -> None:
        try:
            data = {"sensors": [cfg.model_dump() for cfg in self.sensors_config.values()]}
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("Configuración de sensores guardada exitosamente.")
        except Exception as e:
            logger.error(f"Error guardando configuración de sensores: {e}")

    def get_sensor(self, sensor_id: str) -> Optional[BaseSensorAdapter]:
        return self.adapters.get(sensor_id)

    def add_sensor(self, config: SensorConfig) -> None:
        if not _validate_config(config):
            raise ValueError("Configuración de sensor inválida")
        self.sensors_config[config.id] = config
        if config.enabled:
            self.adapters[config.id] = self.create_adapter(config)
        self.save_config()
        logger.info(f"Sensor {config.id} agregado o actualizado.")

    def remove_sensor(self, sensor_id: str) -> None:
        if sensor_id in self.sensors_config:
            del self.sensors_config[sensor_id]
        if sensor_id in self.adapters:
            del self.adapters[sensor_id]
        self.save_config()
        logger.info(f"Sensor {sensor_id} removido.")

    def list_sensors(self) -> List[SensorConfig]:
        return list(self.sensors_config.values())

    def get_all_adapters(self) -> List[BaseSensorAdapter]:
        return list(self.adapters.values())
