# Manual de Procedimiento: Despliegue, Actualización (Git Push/Pull), Configuración y Pruebas

Este documento contiene el procedimiento estándar para desplegar, actualizar y operar el **Sistema de Monitoreo Ambiental** en la Raspberry Pi.

---

## 1. Flujo de Actualización del Código (Git Push y Pull)

Cuando realices modificaciones o mejoras al código en tu computador de desarrollo:

### 1.1 En tu Máquina de Desarrollo (PC / Laptop)
1. Revisa los archivos modificados:
   ```bash
   git status
   ```
2. Añade y confirma los cambios:
   ```bash
   git add .
   git commit -m "Actualización del sistema y simplificación de menú"
   ```
3. Sube los cambios al repositorio remoto en GitHub:
   ```bash
   git push origin main
   ```

---

### 1.2 En la Raspberry Pi
1. Accede por terminal a la carpeta del proyecto en la Pi:
   ```bash
   cd monitoreo-ambiental-upb
   ```
2. Descarga la versión más reciente del código desde GitHub:
   ```bash
   git pull origin main
   ```
3. (Solo si se añadieron nuevas librerías a `requirements.txt`):
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Ejecuta el sistema actualizado:
   ```bash
   python main.py
   ```

---

## 2. Preparación e Instalación Inicial en la Raspberry Pi

```bash
# 1. Clonar el repositorio por primera vez
git clone https://github.com/TU_USUARIO/monitoreo-ambiental-upb.git
cd monitoreo-ambiental-upb

# 2. Crear y activar entorno virtual Python
python3 -m venv venv
source venv/bin/activate

# 3. Instalar librerías
pip install --upgrade pip
pip install -r requirements.txt

# 4. Crear archivo de variables de entorno
cp .env.example .env
```

---

## 3. Opciones del Menú Principal Numerado

Al ejecutar `python main.py`, verás la lista simplificada de 8 opciones:

```text
 MENÚ PRINCIPAL:
 1. Agregar sensor
 2. Remover sensor
 3. Verificar Estado del Sistema
 4. Probar Conectividad Sensores
 5. Tomar Lectura Actual (Bajo demanda)
 6. Iniciar Monitoreo Activo (Ctrl+C para volver)
 7. Generar Archivo de Reporte (CSV)
 8. Salir
```

---

## 4. Guía Detallada de Uso de las Opciones

### Opción 1: Agregar sensor
- Asistente guiado para registrar sensores Davis AirLink (HTTP) o MQTT (ESP32/Pico W).
- Si es la primera vez que agregas un AirLink y no existen credenciales de la API WeatherLink v2, el sistema te las solicitará e ingresará automáticamente en el `.env`.
- Consulta la nube y muestra tus estaciones asociadas para vincular el `Station ID` y la IP local.

### Opción 2: Remover sensor
- Elimina un sensor registrado introduciendo su `sensor_id`.

### Opción 3: Verificar Estado del Sistema
- Despliega una tabla completa con todos los sensores registrados, su tipo, protocolo, IP/Host, `Station ID` y estado de funcionamiento (`✓ ACTIVO` o error).

### Opción 4: Probar Conectividad Sensores
- Realiza pings de prueba HTTP/MQTT hacia cada dispositivo y confirma si responden en la red local.

### Opción 5: Tomar Lectura Actual (Lectura bajo demanda)
- Ejecuta una captura instantánea e inmediata de todos los sensores sin necesidad de dejar corriendo el bucle en segundo plano. Muestra en pantalla los datos de temperatura, humedad, calidad de aire, etc.

### Opción 6: Iniciar Monitoreo Activo (Modo continuo)
- Inicia el bucle de recolección continua en tiempo real.
- Muestra el estado actualizado cada pocos segundos.
- **Para detener la recolección y regresar al menú:** Presiona **`Ctrl + C`**. El recolector se pausará limpiamente y volverás al menú numerado.

### Opción 7: Generar Archivo de Reporte (CSV)
- Exporta las mediciones históricas a un archivo CSV (`data/export_YYYYMMDD_HHMMSS.csv`) indicando los días hacia atrás a consultar.

### Opción 8: Salir
- Finaliza la aplicación realizando un vaciado de datos seguro (*flush*) del buffer SQLite hacia CSV.

---

## 5. Mantenimiento y Registros

- Revisa los logs detallados del sistema en tiempo real con:
  ```bash
  tail -f logs/monitoring.log
  ```
