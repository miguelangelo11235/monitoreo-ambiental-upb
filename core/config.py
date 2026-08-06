import os
from typing import Optional

def save_env_variable(key: str, value: str, env_path: str = ".env") -> None:
    """Guarda o actualiza una variable en el archivo .env y en el entorno actual."""
    os.environ[key] = value
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            updated = True
        else:
            new_lines.append(line)
            
    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")
        
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    
    class Settings(BaseSettings):
        mqtt_broker: str = "127.0.0.1"
        mqtt_port: int = 1883
        csv_path: str = "data/measurements.csv"
        sqlite_path: str = "data/sensor_buffer.db"
        influxdb_url: Optional[str] = None
        influxdb_token: Optional[str] = None
        influxdb_org: Optional[str] = None
        influxdb_bucket: Optional[str] = None
        davis_api_key: Optional[str] = None
        davis_api_secret: Optional[str] = None
        log_level: str = "INFO"
        sensors_config_path: str = "sensors_config.json"

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )

except ImportError:
    try:
        from pydantic import BaseSettings
        
        class Settings(BaseSettings):
            mqtt_broker: str = "127.0.0.1"
            mqtt_port: int = 1883
            csv_path: str = "data/measurements.csv"
            sqlite_path: str = "data/sensor_buffer.db"
            influxdb_url: Optional[str] = None
            influxdb_token: Optional[str] = None
            influxdb_org: Optional[str] = None
            influxdb_bucket: Optional[str] = None
            davis_api_key: Optional[str] = None
            davis_api_secret: Optional[str] = None
            log_level: str = "INFO"
            sensors_config_path: str = "sensors_config.json"

            class Config:
                env_file = ".env"
                env_file_encoding = "utf-8"
                extra = "ignore"

    except ImportError:
        from pydantic import BaseModel

        class Settings(BaseModel):
            mqtt_broker: str = os.getenv("MQTT_BROKER", "127.0.0.1")
            mqtt_port: int = int(os.getenv("MQTT_PORT", 1883))
            csv_path: str = os.getenv("CSV_PATH", "data/measurements.csv")
            sqlite_path: str = os.getenv("SQLITE_PATH", "data/sensor_buffer.db")
            influxdb_url: Optional[str] = os.getenv("INFLUXDB_URL")
            influxdb_token: Optional[str] = os.getenv("INFLUXDB_TOKEN")
            influxdb_org: Optional[str] = os.getenv("INFLUXDB_ORG")
            influxdb_bucket: Optional[str] = os.getenv("INFLUXDB_BUCKET")
            davis_api_key: Optional[str] = os.getenv("DAVIS_API_KEY")
            davis_api_secret: Optional[str] = os.getenv("DAVIS_API_SECRET")
            log_level: str = os.getenv("LOG_LEVEL", "INFO")
            sensors_config_path: str = os.getenv("SENSORS_CONFIG_PATH", "sensors_config.json")


settings = Settings()
