# Arquitectura del Sistema de Monitoreo Ambiental para Campus Universitario

## 1. Introducción y Visión General

Este documento describe la arquitectura de un **sistema de monitoreo ambiental distribuido** diseñado para campus universitarios. El sistema captura datos de múltiples sensores ambientales (temperatura, humedad, presión, etc.), los procesa localmente en una Raspberry Pi, los almacena de forma resiliente, y los visualiza en consola. Está optimizado para ser mantenido por docentes y estudiantes de ingeniería, con énfasis en código legible, modular y fácil de extender.

### Características principales

- **Adquisición multiprotocolo:** soporta sensores vía API REST (Davis AirLink), MQTT y sensores personalizados con ESP32/Pico W
- **Resiliencia:** buffer local SQLite que persiste datos aunque falle la red o la Pi se reinicie
- **Sincronización temporal:** lecturas cada minuto, almacenamiento de datos sincronizados cada 15 minutos (:00, :15, :30, :45)
- **Configuración dinámica:** agregar/remover sensores sin reiniciar el sistema
- **Alertas inteligentes:** notificación de fallos sin interrumpir el procesamiento de otros sensores
- **Escalabilidad:** hasta 5+ sensores inicialmente, fácil expansión a más
- **Almacenamiento híbrido:** CSV local primero, InfluxDB en nube después (cuando sea necesario)

---

## 2. Contexto Técnico

### Infraestructura física

**Hardware:**
- **Hub central:** Raspberry Pi conectada a WiFi del campus
- **Sensores:** distribuidos por el campus en la misma red WiFi
  - 1x Davis AirLink (API REST local)
  - N sensores personalizados (ESP32, Pico W) con protocolo MQTT
- **Broker MQTT:** Mosquitto instalado en la Pi (puerto 1883)

**Red:**
- WiFi del campus (conectividad intermitente en algunas zonas)
- Fallback a API Davis (en nube) si falla conectividad local
- Sin autenticación requerida (datos internos, red controlada)

### Stack tecnológico

- **Lenguaje:** Python 3.10+ (preferencia de desarrolladores)
- **Async:** asyncio + bibliotecas async-first (aiomqtt, httpx async)
- **Validación:** Pydantic (tipado fuerte, validación automática)
- **MQTT:** Mosquitto (broker) + aiomqtt (cliente Python)
- **Almacenamiento:**
  - SQLite (buffer resiliente local)
  - CSV (exportación e histórico local)
  - InfluxDB (opcional, para etapa 2)
- **Versionamiento:** Git + GitHub (pull automático en Pi)

---

## 3. Arquitectura Modular

La aplicación se organiza en **cuatro capas** que progresivamente transforman datos: adquisición → procesamiento → persistencia → visualización.

### 3.1 Capa Física (Hardware)

**Componentes:**
- **Davis AirLink:** sensor profesional que expone API REST local en puerto 8002 (sin autenticación)
- **ESP32/Pico W:** microcontroladores que publican mediciones al broker MQTT
- **Broker MQTT (Mosquitto):** corre en la Pi, actúa como concentrador de mensajes
- **Red WiFi:** conecta todos los dispositivos

**Protocolos:**
- AirLink → HTTP polling (iniciado por Pi)
- ESP32/Pico → MQTT publish (enviados por sensor, suscrito por Pi)

### 3.2 Capa Core (Python - Módulos)

Es donde reside toda la lógica de la aplicación. Se divide en **cinco submódulos funcionales:**

#### **3.2.1 Adaptadores (`adapters/`)**

Son **abstraccciones de sensores específicos**. Cada adaptador implementa una interfaz común (`BaseSensorAdapter`) que define cómo leer datos de un dispositivo físico diferente.

**Clases principales:**

1. **`base_sensor.py` - Interfaz abstracta**
   - Define contrato: `async def read() → Measurement`
   - Cada adaptador concreto hereda de esta clase
   - Permite intercambiar implementaciones sin afectar el resto del sistema

2. **`airlink_adapter.py` - Davis AirLink (HTTP)**
   - Consulta la API REST local del AirLink cada minuto
   - Parsea JSON con temperatura, humedad, presión, velocidad viento
   - Maneja timeout: si no responde en 5s, retorna medición con bandera "no_response"
   - Fallback: si falla, intenta API Davis en nube (requiere API Key)

3. **`mqtt_sensor_adapter.py` - Sensores MQTT personalizados**
   - Se suscribe al topic MQTT del sensor (ej: `campus/lab_a/temp`)
   - Espera mensaje JSON con métricas
   - Timeout de 5s: si no llega dato, retorna medición con bandera "no_response"
   - Permite múltiples sensores MQTT simultáneamente

4. **`fallback_handler.py` - Estrategia de resiliencia**
   - Si adaptador falla N veces consecutivas, intenta fuente alternativa
   - Para AirLink: cambia a API Davis (cuando hay internet)
   - Registra intentos de fallback en log

**Flujo de una lectura:**
```
Sensor físico → Adaptador.read() → Validación → Measurement(sensor_id, timestamp, metrics, quality)
                ↓
            ¿OK? → quality="ok", metrics con datos
            ↓
         ¿Error? → quality="sensor_timeout" o "parsing_error", metrics vacíos
```

#### **3.2.2 Modelos de Datos (`models/`)**

Esquemas estandarizados (Pydantic dataclasses) que garantizan consistencia en todo el sistema.

1. **`measurement.py` - Medición única**
   ```
   Measurement:
     - sensor_id: str          # "airlink_01", "esp32_temp_01"
     - timestamp: datetime     # Momento de lectura
     - location: str           # "Techo Lab A" (referencia)
     - metrics: dict           # {"temperature": 24.5, "humidity": 65.2, ...}
     - quality: str            # "ok", "sensor_timeout", "parsing_error"
     - unit_system: str        # "metric" o "imperial"
   ```

2. **`sensor.py` - Configuración de sensor**
   ```
   SensorConfig:
     - id: str                 # Identificador único
     - name: str               # Nombre descriptivo
     - type: str               # "airlink", "mqtt", "esp32"
     - protocol: str           # "http", "mqtt"
     - ip: str                 # Dirección IP o broker
     - topic: str              # Para MQTT
     - location: str           # Ubicación física
     - enabled: bool           # Si está activo
     - timeout_seconds: int    # Tolerancia de espera
   ```

#### **3.2.3 Servicios (`services/`)**

Componentes que orquestan lógica de negocios: coordinan adaptadores, manejan timing, persisten datos.

1. **`sensor_manager.py` - Gestor de sensores**
   - Lee `sensors_config.json`
   - Instancia adaptadores correspondientes (factory pattern)
   - Mantiene lista de sensores activos en memoria
   - Permite agregar/remover sensores dinámicamente sin reiniciar
   - Valida que cada sensor tenga configuración válida

2. **`mqtt_broker.py` - Gestión del broker MQTT**
   - Inicia Mosquitto en la Pi (si no está corriendo)
   - O conecta a broker remoto (configurado en `.env`)
   - Mantiene healthcheck: verifica conectividad periódica
   - Reinicia broker si cae

3. **`collector_service.py` - Orquestador principal** ⭐
   - **Loop de lectura (cada minuto):**
     - Itera sobre todos los sensores activos
     - Llama `sensor.read()` para cada uno (en paralelo con asyncio)
     - Imprime en consola un log continuo en línea directa: `Timestamp | Sensor | Temp °C | Hum % | PM1.0 | PM2.5 | PM10.0`
     - Captura excepciones: si uno falla, continúa con los demás
     - Escribe medición en el buffer SQLite (incluso con errores)
   - **Loop de sincronización (cada 15 min):**
     - Verifica si el minuto actual es múltiplo del intervalo configurado (`MONGO_SAVE_INTERVAL_MIN`, ej: `:00`, `:15`, `:30`, `:45`)
     - Lee mediciones del buffer desde la última sincronización
     - Sincroniza SQLite -> CSV local, InfluxDB (opcional) y envía el documento BSON completo a MongoDB (`air_quality.raw_measurements`)
   - **Manejo de alertas:** delega la notificación de errores a `alert_service`

4. **`network_service.py` - Diagnósticos de conectividad**
   - `test_http_endpoint(url)` → verifica respuesta HTTP local
   - `test_mqtt_connection(broker)` → verifica conectividad al broker MQTT
   - Utilizado en la interfaz CLI para validar sensores y conectividad

5. **`alert_service.py` - Notificaciones de fallos**
   - Cuando un sensor o base de datos falla: registra el evento en SQLite
   - Escribe en logs detalles del fallo
   - Operaciones no bloqueantes: garantiza que un error en un sensor no detenga a los demás

6. **`log_service.py` - Configuración de Logging**
   - Configura formateadores, manejadores de flujo y niveles de log del sistema (`setup_logger`)

#### **3.2.4 Almacenamiento (`storage/`)**

Abstracción de persistencia: permite cambiar o agregar backends de almacenamiento sin afectar el resto del código.

1. **`base.py` - Interfaz abstracta**
   ```python
   BaseStorage:
     - async write(measurement: Measurement) -> None
     - async read_since(timestamp: datetime) -> List[Measurement]
     - async delete_older_than(days: int) -> None
     - async flush() -> None
   ```

2. **`csv_storage.py` - Almacenamiento en CSV local**
   - Append-only: cada medición es una fila
   - Ruta por defecto: `data/measurements.csv`
   - Usado como formato de exportación e histórico local fácil de procesar en Excel o pandas

3. **`sqlite_buffer.py` - Buffer resiliente local** ⭐
   - Base de datos SQLite local (`data/sensor_buffer.db`) con tablas `measurements` y `events`
   - Resiliencia: las lecturas se persisten de inmediato en disco local
   - Vaciado hacia CSV (`flush_to_csv()`) durante las ventanas de sincronización

4. **`influxdb_storage.py` - Base de datos de series de tiempo**
   - Soporte para InfluxDB Cloud / Local para análisis de series de tiempo y dashboards

5. **`mongodb_storage.py` - Base de datos de documentos MongoDB** ⭐
   - Persistencia asíncrona no bloqueante mediante `asyncio.to_thread`
   - Conexión dinámica a MongoDB Local o MongoDB Atlas (vía `MONGO_URI`)
   - Almacena cada 15 minutos el payload completo obtenido del sensor en la colección `raw_measurements` de la base de datos `air_quality`
   - Preserva metadatos (`did`, `name`, `ts`), mediciones directas y calculadas (`temp`, `hum`, `dew_point`, `pm_1_last`, `pm_2p5_nowcast`, etc.)

6. **`__init__.py` - Exportación de la capa Storage**
   - Exporta de forma unificada `BaseStorage`, `CSVStorage`, `SQLiteBuffer`, `InfluxDBStorage` y `MongoDBStorage`

#### **3.2.5 Configuración y Utilidades (`core/`)**

1. **`config.py` - Carga y gestión de variables globales**
   - Lee el archivo `.env` mediante Pydantic Settings (o fallbacks a `BaseSettings` / `BaseModel`)
   - Función `save_env_variable()` para actualizar dinámicamente variables en el archivo `.env`
   - Variables gestionadas:
     ```env
     MQTT_BROKER=127.0.0.1
     MQTT_PORT=1883
     CSV_PATH=data/measurements.csv
     SQLITE_PATH=data/sensor_buffer.db
     INFLUXDB_URL=https://us-west-2-1.aws.cloud2.influxdata.com
     INFLUXDB_TOKEN=your_token_here
     DAVIS_API_KEY=your_key_here
     DAVIS_API_SECRET=your_secret_here
     LOG_LEVEL=INFO
     MONGO_URI=mongodb://localhost:27017
     MONGO_DB=air_quality
     MONGO_COLLECTION=raw_measurements
     MONGO_SAVE_INTERVAL_MIN=15
     ```

### 3.3 Capa de Presentación (UI)

**CLI interactiva** (`ui/cli.py`):

Menú interactivo en consola con 8 opciones principales:
1. **Agregar sensor:** asistente wizard (AirLink local/nube, MQTT, ESP32)
2. **Remover sensor:** eliminación dinámica por ID
3. **Verificar Estado del Sistema:** reporte tabular de sensores y estado de conectividad a MongoDB, SQLite y CSV
4. **Probar Conectividad Sensores y Base de Datos:** ping a endpoints de sensores y test rápido de ping a MongoDB
5. **Tomar Lectura Actual (Bajo demanda):** ejecuta lectura instantánea y muestra la línea de estado con `ts`, `temp` en °C, `hum`, `PM1.0`, `PM2.5` y `PM10.0`
6. **Iniciar Monitoreo Activo (Ctrl+C para volver):** bucle continuo con salida por línea directa
7. **Generar Archivo de Reporte (CSV):** exportación de histórico por rango de días
8. **Salir:** cierre seguro del sistema y desconexión limpia de storages y servicios

---

### 3.4 Estructura del Proyecto y Propósito de Archivos y Carpetas

A continuación se detalla la estructura física completa del repositorio y el propósito de cada directorio y archivo:

```text
Monitoreo Ambiental UPB/
│
├── main.py                     # Punto de entrada principal del sistema (inicializa MQTT, storages, CollectorService y CLI)
├── sensors_config.json         # Configuración dinámica JSON con la lista de sensores registrados
├── requirements.txt            # Dependencias del proyecto Python (pydantic, aiomqtt, aiohttp, pandas, pymongo, etc.)
├── .env                        # Variables de entorno locales (credenciales, URIs de MongoDB, InfluxDB, etc.)
├── .env.example                # Plantilla de variables de entorno de referencia para el equipo
├── .gitignore                  # Reglas de exclusión de Git (datos locales, logs, entornos virtuales y carpeta Fase 1)
├── README.md                   # Documentación principal de inicio rápido
├── PROCEDIMIENTO.md            # Guía detallada de procedimientos y despliegue del sistema
├── arquitectura_sistema_monitoreo.md # Documento de arquitectura técnica del sistema
│
├── adapters/                   # Capa de adaptadores de adquisición de datos de sensores
│   ├── __init__.py             # Módulo de inicialización del paquete de adaptadores
│   ├── base_sensor.py          # Clase abstracta BaseSensorAdapter que define el contrato read() -> Measurement
│   ├── airlink_adapter.py      # Adaptador HTTP para Davis AirLink (captura metadatos ts/did y payload completo)
│   ├── mqtt_sensor_adapter.py  # Adaptador para sensores MQTT personalizados (ESP32, Pico W)
│   └── fallback_handler.py     # Manejador de redundancia (fallback a WeatherLink Cloud v2 API si falla AirLink local)
│
├── core/                       # Módulo core de configuración central del sistema
│   └── config.py               # Gestión de Settings con Pydantic y guardado dinámico en .env
│
├── models/                     # Modelos de datos y esquemas Pydantic
│   ├── measurement.py          # Modelo de datos Measurement (sensor_id, timestamp, location, metrics, quality)
│   └── sensor.py               # Modelo de datos SensorConfig (id, name, type, protocol, ip, topic, enabled, etc.)
│
├── services/                   # Lógica de negocios y orquestación de procesos
│   ├── sensor_manager.py       # Gestor dinámico de carga, instanciación y edición de sensores en sensors_config.json
│   ├── collector_service.py    # Orquestador del bucle de recolección (60s) y bucle de sincronización (15m a MongoDB/CSV)
│   ├── mqtt_broker.py          # Gestor de inicio, supervisión y reconexión del broker MQTT (Mosquitto)
│   ├── network_service.py      # Diagnósticos de conectividad de red (HTTP y MQTT)
│   ├── alert_service.py        # Registro y notificación de fallos sin interrupción del sistema
│   └── log_service.py          # Configuración del sistema de registros (logging)
│
├── storage/                    # Capa de persistencia y almacenamiento de datos
│   ├── __init__.py             # Módulo de exportación unificada de storages (incluyendo MongoDBStorage)
│   ├── base.py                 # Clase abstracta BaseStorage (write, read_since, delete_older_than, flush)
│   ├── csv_storage.py          # Persistencia histórica append-only en formato CSV local
│   ├── sqlite_buffer.py        # Buffer relacional local SQLite para alta disponibilidad y resiliencia ante cortes
│   ├── influxdb_storage.py     # Conector para base de datos de series de tiempo InfluxDB (opcional)
│   └── mongodb_storage.py      # Almacenamiento en MongoDB (Local/Atlas) guardando payload completo cada 15m
│
├── ui/                         # Capa de interfaz de usuario
│   └── cli.py                  # Menú CLI interactivo de 8 opciones con monitoreo por consola en línea directa
│
├── data/                       # Archivos de datos locales persistidos en runtime (ignorado en Git)
│   ├── measurements.csv        # Archivo CSV acumulativo histórico
│   └── sensor_buffer.db        # Base de datos relacional SQLite de buffer
│
└── logs/                       # Registros de eventos del sistema generados en ejecución (ignorado en Git)
```


---

## 4. Flujos de Datos

### 4.1 Flujo de lectura (cada minuto)

```
collector_service.collect_loop():
  ├─ Para cada sensor en sensor_manager:
  │  ├─ Intenta: measurement = await sensor.read()
  │  │  ├─ AirLink: HTTP GET http://192.168.1.100:8002/...
  │  │  ├─ MQTT: suscribe a topic, espera 5s
  │  │  └─ Retorna Measurement (con quality: ok, error, timeout)
  │  │
  │  ├─ Captura excepciones: si falla, continúa con siguiente sensor
  │  └─ Persiste en SQLite: await sqlite_buffer.write(measurement)
  │
  └─ Espera 60s, repite

Nota: Todos los sensores se leen EN PARALELO usando asyncio.gather()
      Si uno es lento, no retrasa a los demás.
```

### 4.2 Flujo de sincronización (cada 15 minutos)

```
collector_service.sync_loop():
  ├─ Verifica si minuto actual es 0, 15, 30 o 45
  ├─ Lee buffer SQLite desde último sync:
  │  └─ SELECT * FROM measurements WHERE timestamp > last_sync_time
  │
  ├─ Escribe a CSV:
  │  └─ Append a data/measurements.csv
  │
  ├─ Escribe a InfluxDB (si disponible):
  │  └─ HTTP POST a https://influxdb.example.com/api/v1/write
  │
  ├─ Limpia buffer:
  │  └─ DELETE FROM measurements WHERE timestamp < last_sync_time
  │
  └─ Actualiza timestamp de último sync, espera 60s, repite
```

**Ventaja:** si la Pi se cae durante lectura, el buffer preserva datos. Al reiniciar, se syncan cuando sea posible.

### 4.3 Flujo de agregar sensor (desde CLI)

```
user runs: python main.py --add-sensor

CLI interactivo:
  1. Solicita tipo: "airlink" / "mqtt" / "esp32"
  2. Solicita ID: "airlink_02"
  3. Solicita IP: "192.168.1.101"
  4. Solicita ubicación: "Lab de Robótica"
  5. Solicita timeout: 5 (segundos)
  
  6. Testea conexión:
     network_service.test_adapter(adapter_temporal)
     └─ Intenta lectura de prueba, verifica que responda
  
  7. Si OK, agrega a sensors_config.json:
     {
       "id": "airlink_02",
       "type": "airlink",
       "protocol": "http",
       "ip": "192.168.1.101",
       "location": "Lab de Robótica",
       "enabled": true,
       "timeout_seconds": 5
     }
  
  8. Recarga sensor_manager sin reiniciar aplicación principal
  9. Nueva lectura incluye este sensor en próximo ciclo (< 60s)
```

### 4.4 Flujo de fallo y recuperación

```
Escenario 1: Sensor offline
  1. collector_service intenta read() de ESP32
  2. Timeout después de 5s → excepción TimeoutError
  3. Captura excepción, retorna Measurement(quality="sensor_timeout")
  4. Persiste en SQLite: metrics={}, quality="sensor_timeout"
  5. alert_service.notify("esp32_temp_01 no responde")
     └─ Escribe en SQLite.events + log
  6. Continúa con siguiente sensor (NO se bloquea)

Escenario 2: AirLink falla, fallback a Davis API
  1. HTTP GET a 192.168.1.100:8002 falla (red local caída)
  2. fallback_handler.fetch_from_davis_api(api_key, station_id)
  3. Davis API responde con datos de hace 10 min (su API tiene delay)
  4. Persiste en SQLite: quality="davis_fallback"
  5. Próximo sync a CSV incluye nota que fue fallback

Escenario 3: Pi se reinicia
  1. SQLite buffer tiene mediciones no syncronizadas
  2. Al reinicar, collector_service carga buffer en memoria
  3. Próximo ciclo de sync (< 15 min) los escribe a CSV/InfluxDB
  4. No se pierde nada
```

---

## 5. Estructura de Archivos Detallada

### 5.1 Raíz del proyecto

```
airlink_project/
├── .gitignore                          # Excluye .env, __pycache__, data/
├── .env.example                        # Plantilla de configuración
├── .env                                # (NO committed) Valores locales
├── requirements.txt                    # Dependencias Python
├── README.md                           # Setup y quickstart
└── main.py                             # Punto de entrada

# Instalación:
# pip install -r requirements.txt
# python main.py
```

### 5.2 Estructura de directorios

```
core/
├── __init__.py
└── config.py
    └── class Settings(BaseSettings):
        ├── mqtt_broker: str
        ├── csv_path: str
        ├── sqlite_path: str
        ├── log_level: str
        └── (carga de .env y env vars)

models/
├── __init__.py
├── measurement.py
│   └── class Measurement:
│       ├── sensor_id: str
│       ├── timestamp: datetime
│       ├── location: str
│       ├── metrics: dict
│       ├── quality: str
│       └── unit_system: str
│
└── sensor.py
    └── class SensorConfig:
        ├── id: str
        ├── name: str
        ├── type: str
        ├── protocol: str
        ├── ip: str
        ├── topic: str (opcional, para MQTT)
        ├── location: str
        ├── enabled: bool
        └── timeout_seconds: int

adapters/
├── __init__.py
├── base_sensor.py
│   └── class BaseSensorAdapter(ABC):
│       └── async def read() -> Measurement
│
├── airlink_adapter.py
│   ├── class AirlinkAdapter(BaseSensorAdapter):
│   │   ├── async def read() -> Measurement
│   │   ├── async def fetch_from_local_api() -> dict
│   │   └── async def fallback_to_davis_api() -> dict
│   └── def parse_airlink_response(json_data) -> dict
│
├── mqtt_sensor_adapter.py
│   ├── class MQTTSensorAdapter(BaseSensorAdapter):
│   │   ├── async def read() -> Measurement
│   │   ├── async def subscribe_and_wait(topic, timeout=5s) -> dict
│   │   └── def parse_mqtt_payload(json_payload) -> dict
│   └── class MQTTClient:
│       ├── async def connect(broker_ip)
│       └── async def subscribe(topic)
│
└── fallback_handler.py
    ├── class FallbackHandler:
    │   ├── async def try_fallback(adapter, error_count)
    │   └── async def fetch_from_davis_api() -> dict
    └── def log_fallback_attempt()

services/
├── __init__.py
├── sensor_manager.py
│   ├── class SensorManager:
│   │   ├── load_from_config(config_path: str) -> List[SensorConfig]
│   │   ├── create_adapter(config: SensorConfig) -> BaseSensorAdapter
│   │   ├── get_sensor(sensor_id: str) -> BaseSensorAdapter
│   │   ├── add_sensor(config: SensorConfig)
│   │   ├── remove_sensor(sensor_id: str)
│   │   └── list_sensors() -> List[SensorConfig]
│   └── def _validate_config(config: SensorConfig) -> bool
│
├── mqtt_broker.py
│   ├── class MQTTBrokerManager:
│   │   ├── async def start()
│   │   ├── async def is_running() -> bool
│   │   ├── async def healthcheck() -> bool
│   │   └── async def restart()
│   └── def _spawn_mosquitto_process()
│
├── collector_service.py  ⭐ PIEZA CENTRAL
│   ├── class CollectorService:
│   │   ├── async def start()
│   │   ├── async def collect_loop()
│   │   │   ├─ Lee sensores cada 60s
│   │   │   ├─ Persiste en SQLite
│   │   │   └─ Maneja excepciones sin bloquear
│   │   │
│   │   ├── async def sync_loop()
│   │   │   ├─ Detecta :00, :15, :30, :45
│   │   │   ├─ Flush SQLite → CSV
│   │   │   ├─ Flush SQLite → InfluxDB (si disponible)
│   │   │   └─ Limpia buffer
│   │   │
│   │   ├── async def shutdown()
│   │   └── def get_status() -> dict
│   │
│   └── def _should_sync() -> bool
│
├── network_service.py
│   ├── class NetworkService:
│   │   ├── async def ping(ip: str, timeout=2s) -> bool
│   │   ├── async def test_http_endpoint(url, timeout=5s) -> bool
│   │   ├── async def test_mqtt_connection(broker, topic) -> bool
│   │   └── async def check_internet_connectivity() -> bool
│   │
│   └── def get_local_ip() -> str
│
├── alert_service.py
│   ├── class AlertService:
│   │   ├── async def notify_sensor_failure(sensor_id, error)
│   │   ├── async def notify_network_issue(issue)
│   │   ├── async def notify_db_error(error)
│   │   ├── send_to_stdout(message)
│   │   ├── send_to_email(message)  # (opcional)
│   │   └── async def write_event_to_db(event_dict)
│   │
│   └── def format_alert_message(sensor_id, error, timestamp) -> str
│
└── log_service.py
    ├── class LogService:
    │   ├── def setup_logger(name, level)
    │   ├── logger.info(message)
    │   ├── logger.warning(message)
    │   └── logger.error(message)
    │
    └── loggers: collector, adapters, services, storage

storage/
├── __init__.py
├── base.py
│   └── class BaseStorage(ABC):
│       ├── async def write(measurement: Measurement)
│       ├── async def read_since(timestamp: datetime) -> List[Measurement]
│       ├── async def delete_older_than(days: int)
│       └── async def flush()
│
├── csv_storage.py
│   ├── class CSVStorage(BaseStorage):
│   │   ├── async def write(measurement)
│   │   ├── async def read_since(timestamp) -> List[Measurement]
│   │   └── async def export_range(start, end) -> pd.DataFrame
│   │
│   └── def _ensure_headers()
│
├── sqlite_buffer.py  ⭐ RESILIENCIA
│   ├── class SQLiteBuffer(BaseStorage):
│   │   ├── async def write(measurement)
│   │   ├── async def read_since(timestamp) -> List[Measurement]
│   │   ├── async def read_all() -> List[Measurement]
│   │   ├── async def flush_to_csv()
│   │   ├── async def clear()
│   │   └── async def count() -> int
│   │
│   └── def _create_tables()
│
└── influxdb_storage.py
    └── class InfluxDBStorage(BaseStorage):
        ├── async def write(measurement)
        ├── async def read_since(timestamp) -> List[Measurement]
        ├── async def query(sensor_id, start, end) -> List[Measurement]
        └── async def connect(url, token, org, bucket)

ui/
├── __init__.py
└── cli.py
    ├── class CLIMenu:
    │   ├── async def show_main_menu()
    │   ├── async def list_sensors()
    │   ├── async def add_sensor_wizard()
    │   ├── async def remove_sensor()
    │   ├── async def view_measurements()
    │   ├── async def export_data()
    │   ├── async def test_connectivity()
    │   ├── async def view_logs()
    │   └── async def shutdown()
    │
    └── def format_table(headers, rows) -> str

main.py
└── async def main():
    ├─ Carga config y logger
    ├─ Inicia MQTT broker
    ├─ Instancia sensor_manager
    ├─ Inicia collector_service (tasks: collect + sync)
    ├─ Inicia CLI menu
    └─ Graceful shutdown on Ctrl+C

sensors_config.json
└── {
      "sensors": [
        {
          "id": "airlink_01",
          "name": "Davis AirLink - Lab A",
          "type": "airlink",
          "protocol": "http",
          "ip": "192.168.1.100",
          "location": "Techo Lab A",
          "enabled": true,
          "timeout_seconds": 5
        },
        {
          "id": "esp32_temp_01",
          "name": "ESP32 Temperatura",
          "type": "mqtt",
          "protocol": "mqtt",
          "broker": "127.0.0.1",
          "topic": "campus/lab_a/temperature",
          "location": "Esquina Lab A",
          "enabled": true,
          "timeout_seconds": 5
        }
      ]
    }

data/
├── measurements.csv
│   └── timestamp,sensor_id,location,metric_name,metric_value,quality
│       2024-08-06T14:00:00,airlink_01,Techo Lab A,temperature,24.5,ok
│       2024-08-06T14:00:00,airlink_01,Techo Lab A,humidity,62.3,ok
│       2024-08-06T14:00:00,esp32_temp_01,Esquina Lab A,temperature,25.1,ok
│       ...
│
└── sensor_buffer.db
    ├── Table: measurements
    │   ├── id: INTEGER PRIMARY KEY
    │   ├── timestamp: DATETIME
    │   ├── sensor_id: TEXT
    │   ├── location: TEXT
    │   ├── metrics: JSON
    │   ├── quality: TEXT
    │   └── synced: BOOLEAN
    │
    └── Table: events
        ├── id: INTEGER PRIMARY KEY
        ├── timestamp: DATETIME
        ├── event_type: TEXT (sensor_alert, network_error, db_error)
        ├── sensor_id: TEXT (nullable)
        └── message: TEXT

logs/
└── monitoring.log
    2024-08-06T14:00:00 [INFO] Collector started
    2024-08-06T14:00:01 [INFO] airlink_01: read successful, temp=24.5C
    2024-08-06T14:00:02 [WARNING] esp32_temp_01: timeout (no MQTT message)
    2024-08-06T14:00:03 [INFO] Measurements persisted to SQLite (2 records)
    ...
```

---

## 6. Ciclo de Vida de la Aplicación

### 6.1 Inicio (startup)

```
python main.py

1. Load .env y Settings
2. Setup logging
3. Instancia sensor_manager → carga sensors_config.json
4. Instancia MQTT broker (Mosquitto)
   └─ Si no está corriendo, lo inicia
5. Instancia storage backends (CSV, SQLite, InfluxDB si disponible)
6. Instancia alert_service
7. Crea collector_service
8. Lanza dos tasks asyncio:
   └─ collect_loop() → cada 60s
   └─ sync_loop() → cada 15 min (con validación de minutos)
9. Muestra CLI menu interactivo
10. Espera input del usuario o Ctrl+C para salir
```

### 6.2 Operación normal (steady-state)

- **Cada 60 segundos:** collector_service intenta leer todos los sensores (en paralelo)
- **Cada lectura:** datos se persisten en SQLite (o se registra el error)
- **Cada 15 min:** flush a CSV y/o InfluxDB, limpia SQLite
- **Si hay error:** se registra en eventos, se notifica al usuario, continúa
- **CLI:** usuario puede agregar/remover sensores, ver estado, exportar datos en cualquier momento

### 6.3 Shutdown (parada controlada)

```
Usuario presiona Ctrl+C

1. Signal handler captura SIGINT
2. Stopea collector tasks (collect_loop, sync_loop)
3. Completa cualquier escritura pendiente en SQLite
4. Flush final a CSV (si hay datos no syncronizados)
5. Cierra conexiones (MQTT, base de datos)
6. Goodbye message, exit(0)

Nota: Si se interrumpe abruptamente (kill -9), SQLite sigue íntegro.
```

---

## 7. Configuración Paso a Paso

### 7.1 Setup inicial en Raspberry Pi

```bash
# 1. Clonar repositorio
git clone https://github.com/tu-repo/airlink_project.git
cd airlink_project

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Crear .env desde plantilla
cp .env.example .env

# 5. Editar .env con tus datos
nano .env

# 6. Instalar Mosquitto
sudo apt update
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto

# 7. Probar que todo funciona
python main.py

# 8. (Opcional) Configurar para que corra al boot
# Agregar a crontab: @reboot cd /home/pi/airlink_project && source venv/bin/activate && python main.py
```

### 7.2 Configurar primer sensor (AirLink)

```bash
python main.py

>>> Menú: [A]gregar [R]emover [V]er [E]xportar [T]est [Q]uit: A

Tipo de sensor (airlink/mqtt/esp32): airlink
ID único: airlink_01
Nombre: Davis AirLink - Techo Lab A
IP del sensor: 192.168.1.100
Ubicación: Techo Lab A
Timeout (segundos) [5]: 5

Testeando conexión... 
✓ Conectado a http://192.168.1.100:8002
✓ Sensor guardado en sensors_config.json

>>> Menú: [A]gregar [R]emover [V]er [E]xportar [T]est [Q]uit: V

SENSORES ACTIVOS:
┌──────────────┬──────────────────┬────────┐
│ ID           │ Ubicación        │ Estado │
├──────────────┼──────────────────┼────────┤
│ airlink_01   │ Techo Lab A      │ ✓ OK   │
└──────────────┴──────────────────┴────────┘

>>> Primera medición llegará en ~60s
```

### 7.3 Agregar sensor MQTT (ESP32)

```bash
# 1. Programar ESP32 para publicar a MQTT
# Código ejemplo (Arduino):
/*
#include <WiFi.h>
#include <PubSubClient.h>

const char* ssid = "Campus_WiFi";
const char* password = "password";
const char* mqtt_broker = "192.168.1.50";  // IP de Pi
const char* topic = "campus/lab_a/temperature";

WiFiClient espClient;
PubSubClient client(espClient);

void setup() {
  WiFi.begin(ssid, password);
  client.setServer(mqtt_broker, 1883);
}

void loop() {
  if (!client.connected()) {
    client.connect("ESP32_TEMP");
  }
  client.loop();
  
  float temp = readTemperature();
  String payload = "{\"temperature\": " + String(temp) + "}";
  client.publish(topic, payload.c_str());
  delay(60000);  // Cada minuto
}
*/

# 2. Agregar sensor en CLI
python main.py

>>> Menú: [A]gregar [R]emover [V]er [E]xportar [T]est [Q]uit: A

Tipo de sensor (airlink/mqtt/esp32): mqtt
ID único: esp32_temp_01
Nombre: Temperatura Lab A
Broker MQTT: 127.0.0.1
Topic MQTT: campus/lab_a/temperature
Ubicación: Esquina Lab A
Timeout (segundos) [5]: 5

Testeando conexión...
✓ Broker disponible en 127.0.0.1:1883
✓ Sensor guardado en sensors_config.json
```

---

## 8. Manejo de Errores y Resiliencia

### 8.1 Escenarios de fallo y recuperación

| Escenario | Síntoma | Acción del sistema |
|-----------|---------|-------------------|
| Sensor offline (no responde) | TimeoutError después de 5s | Registra medición con quality="sensor_timeout", continúa con otros sensores |
| WiFi intermitente | Lectura falla, próxima retry en 60s | Buffer SQLite preserva datos, sync cuando hay conectividad |
| AirLink falla | HTTP timeout | Intenta fallback a Davis API (requiere internet) |
| InfluxDB no disponible | POST request falla | Continúa escribiendo a CSV, InfluxDB se reintentará en próximo sync |
| Pi se reinicia | Datos no syncronizados en buffer | Al iniciar, carga buffer y synca en próximo ciclo de 15 min |
| Corte de poder (abrupto) | SQLite puede corromper si ocurre mid-write | SQLite tiene transacciones, riesgo mínimo; data/sensor_buffer.db-journal ayuda |

### 8.2 Logs y debugging

```bash
# Ver logs en tiempo real
tail -f logs/monitoring.log

# O desde CLI
>>> Menú: [A]gregar [R]emover [V]er [E]xportar [T]est [Q]uit: L
# Muestra últimos 50 eventos

# Niveles de log (en .env):
LOG_LEVEL=DEBUG    # Muy verboso, útil para debugging
LOG_LEVEL=INFO     # Recomendado para producción
LOG_LEVEL=WARNING  # Solo problemas serios
LOG_LEVEL=ERROR    # Solo fallos críticos
```

### 8.3 Backup de datos

```bash
# Hacer backup de SQLite y CSV cada semana
crontab -e

# Agregar línea:
0 2 * * 0 cp /home/pi/airlink_project/data/sensor_buffer.db /backup/sensor_buffer_$(date +\%Y-\%m-\%d).db.bak
0 2 * * 0 cp /home/pi/airlink_project/data/measurements.csv /backup/measurements_$(date +\%Y-\%m-\%d).csv.bak
```

---

## 9. Crecimiento y Extensibilidad

### 9.1 De aquí a 3 meses

**Fase 1 (Actual):**
- AirLink + CSV/SQLite
- CLI básica
- 5 sensores

**Fase 2 (Mes 2):**
- Agregar 3-5 sensores MQTT personalizados
- Dashboard web básico (Flask o FastAPI)
- Exportación a InfluxDB

**Fase 3 (Mes 3):**
- REST API pública (con autenticación)
- Grafana para visualización
- Alertas por email/SMS

### 9.2 Agregar nuevo tipo de sensor

1. Crear `adapters/new_sensor_adapter.py`
2. Heredar de `BaseSensorAdapter`
3. Implementar `async def read() → Measurement`
4. Agregar tipo a `sensor_manager.py` factory
5. Actualizar `sensors_config.json` schema (validación)
6. Listo; no necesitas tocar collector_service

### 9.3 Migrar a InfluxDB

```python
# storage/influxdb_storage.py ya existe (stub)
# Solo completar métodos:
# 1. async def write(measurement)
# 2. async def connect(url, token, org, bucket)
# 3. Cambiar en collector_service.sync_loop() a usar influxdb_storage

# En main.py:
influx = InfluxDBStorage(url=settings.influxdb_url, token=settings.influxdb_token)
await collector.register_storage(influx)
```

---

## 10. Ventajas de esta Arquitectura

✅ **Modular:** cada adaptador/storage es independiente  
✅ **Testeable:** interfaces abstractas facilitan mocks  
✅ **Resiliente:** buffer SQLite no pierde datos  
✅ **Escalable:** agregar sensores sin tocar código existente  
✅ **Entendible:** módulos obvios, nombres claros, código limpio  
✅ **Educativa:** excelente para que estudiantes aprendan patrones de diseño  
✅ **Mantenible:** cambios localizados en módulos específicos  
✅ **Multi-protocolo:** HTTP, MQTT, fácil agregar CoAP/LoRa/etc  
✅ **Flexible:** híbrida local + nube, cuando sea necesario  

---

## 11. Próximos Pasos

1. **Crear repositorio en GitHub** con estructura de directorios
2. **Implementar módulos en este orden:**
   - `core/config.py` → `models/` → `adapters/base_sensor.py`
   - `adapters/airlink_adapter.py` → prueba con AirLink real
   - `storage/csv_storage.py` + `storage/sqlite_buffer.py`
   - `services/collector_service.py` → loop principal
   - `services/sensor_manager.py` + `ui/cli.py` → gestión dinámica

3. **Testing:** escribir unit tests para cada adaptador
4. **Documentación:** READMEs en cada módulo, ejemplos de uso
5. **Deployment:** configurar para correr al boot de Pi, systemd service

---

## 12. Apéndice: Dependencias Python

```
# requirements.txt
pydantic==2.4.2           # Validación y tipado
pydantic-settings==2.0.3  # Config desde .env
aiomqtt==0.16.1          # MQTT async client
aiohttp==3.9.0           # HTTP async client
asyncio-contextmanager   # Context managers async
pandas==2.1.0            # CSV/datos (opcional)
influxdb-client==1.18.0  # InfluxDB (opcional, agregar luego)
python-dotenv==1.0.0     # Carga .env
```

