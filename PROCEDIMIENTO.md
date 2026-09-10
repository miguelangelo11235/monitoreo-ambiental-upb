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

# 4. Crear archivo de variables de entorno y configurar MongoDB
cp .env.example .env
```

### Configuración de MongoDB en la Raspberry Pi

Por defecto, el archivo `.env` se crea con la ruta local: `MONGO_URI=mongodb://localhost:27017`.

Si la validación de conexión falla al ejecutar `python main.py`, tienes dos opciones según tu infraestructura:

#### Opción A: Usar MongoDB Atlas en la Nube (Recomendado)
1. Edita el archivo `.env` en la Raspberry Pi o usa la **Opción 4 (Probar Conectividad)** del menú interactivo para ingresar la URI de MongoDB Atlas:
   ```env
   MONGO_URI=mongodb+srv://<usuario>:<contraseña>@cluster.mongodb.net/air_quality?retryWrites=true&w=majority
   MONGO_DB=air_quality
   MONGO_COLLECTION=raw_measurements
   MONGO_SAVE_INTERVAL_MIN=15
   ```
2. **Importante en MongoDB Atlas:** Asegúrate de agregar la dirección IP pública de la Raspberry Pi (o habilitar `0.0.0.0/0` temporalmente) en la sección **Network Access** de MongoDB Atlas.

#### Opción B: Ejecutar MongoDB localmente en la Raspberry Pi
1. Comprueba si el servicio de MongoDB local está activo en la Pi:
   ```bash
   sudo systemctl status mongod
   ```
2. Si no está iniciado o instalado, inícialo con:
   ```bash
   sudo systemctl start mongod
   sudo systemctl enable mongod
   ```

---


## 3. Opciones del Menú Principal Numerado

Al ejecutar `python main.py`, verás la lista del menú principal de 9 opciones:

```text
 MENÚ PRINCIPAL:
 1. Agregar sensor
 2. Remover sensor
 3. Verificar Estado del Sistema
 4. Probar Conectividad Sensores
 5. Tomar Lectura Actual (Bajo demanda)
 6. Iniciar Monitoreo Activo (Ctrl+C para volver)
 7. Generar Archivo de Reporte (CSV)
 8. Configurar Base de Datos MongoDB (y Probar Conexión)
 9. Salir
```

---

## 4. Guía Detallada de Uso de las Opciones

### Opción 1: Agregar sensor
- Asistente guiado para registrar sensores Davis AirLink (HTTP) o MQTT (ESP32/Pico W).
- Si es la primera vez que agregas un AirLink y no existen credenciales de la API WeatherLink v2, el sistema te las solicitará e ingresará automáticamente en el `.env`.
- Consulta la nube y muestra tus estaciones asociadas para vincular el `Station ID` y la IP local.

### Opción 2: Remover sensor
- Muestra una tabla con los sensores registrados actualmente y permite eliminar un sensor introduciendo su número de índice o `sensor_id`.

### Opción 3: Verificar Estado del Sistema
- Despliega una tabla completa con todos los sensores registrados, su tipo, protocolo, IP/Host, `Station ID`, estado de funcionamiento y estado de conexión a MongoDB, SQLite y CSV.

### Opción 4: Probar Conectividad Sensores
- Realiza pings de prueba ICMP/HTTP/MQTT hacia cada dispositivo y confirma si responden en la red local.

### Opción 5: Tomar Lectura Actual (Lectura bajo demanda)
- Permite seleccionar un sensor específico o leer todos los sensores en ese instante sin iniciar el monitoreo continuo.

### Opción 6: Iniciar Monitoreo Activo (Modo continuo)
- Solicita el intervalo de recolección en minutos (ej: 1, 2, 5 minutos).
- Inicia el bucle de recolección continua en tiempo real sin alarmas redundantes.
- **Para detener la recolección y regresar al menú:** Presiona **`Ctrl + C`**.

### Opción 7: Generar Archivo de Reporte (CSV)
- Exporta las mediciones históricas a un archivo CSV (`data/export_YYYYMMDD_HHMMSS.csv`) indicando los días hacia atrás a consultar.

### Opción 8: Configurar Base de Datos MongoDB (y Probar Conexión)
- Muestra el estado actual de la conexión a MongoDB y la modalidad de guardado.
- Permite elegir la modalidad de registro:
  - **Horas cerradas (Recomendado):** Alinea los registros a minutos exactos del reloj:
    - **10 min:** `:00`, `:10`, `:20`, `:30`, `:40`, `:50`
    - **15 min:** `:00`, `:15`, `:30`, `:45` (Por defecto)
    - **20 min:** `:00`, `:20`, `:40`
    - **30 min:** `:00`, `:30`
    - **60 min:** `:00`
  - **Intervalo abierto:** Envía mediciones a intervalos regulares continuos de $N$ minutos transcurridos a partir de la hora de inicio.
- Asistente directo para ingresar **Usuario y Contraseña de MongoDB Atlas** o la URI completa y ejecutar una **prueba de conexión inmediata**.

### Opción 9: Salir
- Finaliza la aplicación realizando un vaciado de datos seguro (*flush*) del buffer SQLite hacia CSV y cerrado limpio de servicios.


---

## 5. Mantenimiento y Registros

- Revisa los logs detallados del sistema en tiempo real con:
  ```bash
  tail -f logs/monitoring.log
  ```
