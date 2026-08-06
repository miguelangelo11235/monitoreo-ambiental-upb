# Sistema de Monitoreo Ambiental para Campus Universitario

Sistema distribuido de monitoreo ambiental desarrollado en Python 3.10+ para Raspberry Pi y microcontroladores (Davis AirLink, ESP32, Pico W).

## Arquitectura y Características

- **Adquisición Multiprotocolo:** Soporta HTTP REST (Davis AirLink) y MQTT (ESP32/Pico W).
- **Resiliencia Local:** Buffer SQLite que guarda transaccionalmente cada lectura frente a caídas de red o energía.
- **Sincronización Periódica:** Vacía mediciones del buffer hacia CSV (e InfluxDB si se dispone de nube) cada 15 minutos (`:00`, `:15`, `:30`, `:45`).
- **Administración Dinámica:** CLI interactivo para agregar/eliminar sensores y ver datos en tiempo real sin reiniciar la aplicación.
- **Fallbacks Inteligentes:** Mecanismo de contingencia a Davis Cloud API si el sensor local AirLink falla.

## Estructura de Directorios

```
Monitoreo Ambiental UPB/
├── .env.example              # Plantilla de variables de entorno
├── .env                      # Variables locales
├── requirements.txt          # Dependencias de Python
├── sensors_config.json       # Configuración dinámica de sensores
├── README.md                 # Guía y documentación
├── main.py                   # Punto de entrada principal
├── core/                     # Configuración global
├── models/                   # Dataclasses y esquemas Pydantic
├── adapters/                 # Adaptadores de sensores (AirLink, MQTT)
├── storage/                  # Persistencia (CSV, SQLite Buffer, InfluxDB)
├── services/                 # Gestores, colectores, alertas y diagnósticos
├── ui/                       # CLI interactivo
├── data/                     # Base de datos y archivos CSV
└── logs/                     # Registros del sistema
```

## Instalación y Ejecución

1. **Clonar repositorio y crear entorno virtual:**
   ```bash
   python -m venv venv
   # En Windows:
   venv\Scripts\activate
   # En Linux/Raspberry Pi:
   source venv/bin/activate
   ```

2. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar variables de entorno:**
   ```bash
   cp .env.example .env
   ```

4. **Ejecutar el sistema:**
   ```bash
   python main.py
   ```
