import sys
import asyncio
import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from models.sensor import SensorConfig
from services.sensor_manager import SensorManager
from services.collector_service import CollectorService
from services.network_service import NetworkService, get_local_ip
from adapters.fallback_handler import FallbackHandler
from storage.sqlite_buffer import SQLiteBuffer
from storage.csv_storage import CSVStorage
from storage.mongodb_storage import MongoDBStorage
from core.config import settings, save_env_variable

logger = logging.getLogger("ui.cli")


def format_table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "No hay datos para mostrar."

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    header_line = "│ " + " │ ".join(f"{str(headers[i]):<{col_widths[i]}}" for i in range(len(headers))) + " │"
    separator = "├─" + "─┼─".join("─" * col_widths[i] for i in range(len(headers))) + "─┤"
    top_border = "┌─" + "─┬─".join("─" * col_widths[i] for i in range(len(headers))) + "─┐"
    bottom_border = "└─" + "─┴─".join("─" * col_widths[i] for i in range(len(headers))) + "─┘"

    row_lines = []
    for row in rows:
        row_str = "│ " + " │ ".join(f"{str(row[i]):<{col_widths[i]}}" for i in range(len(row))) + " │"
        row_lines.append(row_str)

    return "\n".join([top_border, header_line, separator] + row_lines + [bottom_border])


class CLIMenu:
    """Menú interactivo CLI con soporte para monitoreo de MongoDB y sensores."""

    def __init__(
        self,
        collector_service: CollectorService,
        sensor_manager: SensorManager,
        sqlite_buffer: SQLiteBuffer,
        csv_storage: CSVStorage,
        mongo_storage: Optional[MongoDBStorage] = None
    ):
        self.collector_service = collector_service
        self.sensor_manager = sensor_manager
        self.sqlite_buffer = sqlite_buffer
        self.csv_storage = csv_storage
        self.mongo_storage = mongo_storage
        self.fallback_handler = FallbackHandler()


    async def _async_input(self, prompt: str) -> str:
        return await asyncio.to_thread(input, prompt)

    async def _ensure_weatherlink_credentials(self) -> tuple[str, str]:
        api_key = settings.davis_api_key or ""
        api_secret = settings.davis_api_secret or ""

        if not api_key or api_key == "your_key_here" or not api_secret or api_secret == "your_secret_here":
            print("\n🔑  [CONFIGURACIÓN WEATHERLINK v2 API]")
            print("Se requieren tus credenciales WeatherLink v2 de https://www.weatherlink.com/account\n")
            
            new_key = await self._async_input("Ingrese su API Key de WeatherLink: ")
            new_secret = await self._async_input("Ingrese su API Secret de WeatherLink: ")

            new_key = new_key.strip()
            new_secret = new_secret.strip()

            if new_key and new_secret:
                save_env_variable("DAVIS_API_KEY", new_key)
                save_env_variable("DAVIS_API_SECRET", new_secret)
                settings.davis_api_key = new_key
                settings.davis_api_secret = new_secret
                print("✓ Credenciales guardadas exitosamente en .env\n")
                return new_key, new_secret
            else:
                print("⚠️ Credenciales omitidas.\n")
                return api_key, api_secret
        return api_key, api_secret

    async def add_sensor_wizard(self) -> None:
        """Opción 1: Agregar sensor."""
        print("\n--- ASISTENTE PARA AGREGAR SENSOR ---")
        sensor_type = await self._async_input("Tipo de sensor (airlink/mqtt/esp32): ")
        sensor_type = sensor_type.strip().lower()
        if sensor_type not in ["airlink", "mqtt", "esp32"]:
            print("❌ Tipo de sensor no soportado.")
            return

        station_id = None
        ip = "127.0.0.1"

        if sensor_type == "airlink":
            key, secret = await self._ensure_weatherlink_credentials()
            if key and secret:
                print("Consultando estaciones registradas en tu cuenta WeatherLink API v2...")
                stations = await self.fallback_handler.fetch_stations(key, secret)
                if stations:
                    print("\nEstaciones encontradas en tu cuenta WeatherLink:")
                    st_headers = ["Índice", "Station ID", "UUID", "Nombre Estación"]
                    st_rows = []
                    for idx, st in enumerate(stations, 1):
                        st_rows.append([idx, st.get("station_id"), st.get("station_id_uuid", "-"), st.get("station_name", "Sin nombre")])
                    print(format_table(st_headers, st_rows))
                    
                    sel = await self._async_input("\nSeleccione número de estación (o Enter para omitir): ")
                    if sel.strip().isdigit():
                        st_idx = int(sel.strip()) - 1
                        if 0 <= st_idx < len(stations):
                            chosen = stations[st_idx]
                            station_id = str(chosen.get("station_id") or chosen.get("station_id_uuid"))
                            print(f"✓ Vinculada con Station ID: {station_id}")

            ip_input = await self._async_input("IP local del AirLink (ej: 192.168.1.100) [Enter si usas sólo nube]: ")
            if ip_input.strip():
                ip = ip_input.strip()

        else:
            ip_input = await self._async_input("IP o Broker (ej: 192.168.1.100 / 127.0.0.1): ")
            if ip_input.strip():
                ip = ip_input.strip()

        sensor_id = await self._async_input("ID único del sensor (ej: airlink_01, esp32_01): ")
        name = await self._async_input("Nombre descriptivo: ")
        location = await self._async_input("Ubicación física: ")

        topic = None
        protocol = "http"
        if sensor_type in ["mqtt", "esp32"]:
            protocol = "mqtt"
            topic = await self._async_input("Topic MQTT (ej: campus/lab_a/temperature): ")

        timeout_str = await self._async_input("Timeout en segundos [5]: ")
        timeout_seconds = int(timeout_str.strip()) if timeout_str.strip().isdigit() else 5

        print("\nTesteando conexión...")
        online = False
        if protocol == "http" and ip != "127.0.0.1":
            url = f"http://{ip}:8002/v1/current_conditions"
            online = await NetworkService.test_http_endpoint(url, timeout=2.0)
            if online:
                print("✓ Conexión exitosa con API local AirLink.")
            else:
                print("⚠️ Advertencia: No se detectó AirLink en la IP local especificada.")
        elif station_id:
            print("✓ Registrado para lectura/fallback vía WeatherLink Cloud v2 API.")

        config = SensorConfig(
            id=sensor_id.strip(),
            name=name.strip(),
            type=sensor_type,
            protocol=protocol,
            ip=ip,
            broker=ip if protocol == "mqtt" else "127.0.0.1",
            topic=topic.strip() if topic else None,
            station_id=station_id,
            location=location.strip(),
            enabled=True,
            timeout_seconds=timeout_seconds
        )

        self.sensor_manager.add_sensor(config)
        print(f"✓ Sensor '{sensor_id}' guardado en sensors_config.json exitosamente.\n")

    async def remove_sensor(self) -> None:
        """Opción 2: Remover sensor."""
        sensors = self.sensor_manager.list_sensors()
        if not sensors:
            print("\n⚠️ No hay sensores registrados para remover.\n")
            return

        print("\n--- SENSORES REGISTRADOS ACTUALMENTE ---")
        headers = ["#", "ID", "Nombre", "Tipo", "Protocolo", "IP / Host", "Ubicación"]
        rows = [[idx, s.id, s.name, s.type, s.protocol, s.ip, s.location] for idx, s in enumerate(sensors, 1)]
        print(format_table(headers, rows))

        sensor_input = await self._async_input("\nIngrese el número de índice o el ID del sensor a remover (o Enter para cancelar): ")
        sensor_input = sensor_input.strip()

        if not sensor_input:
            print("Operación cancelada.\n")
            return

        target_id = None
        if sensor_input.isdigit():
            idx = int(sensor_input) - 1
            if 0 <= idx < len(sensors):
                target_id = sensors[idx].id
        else:
            if sensor_input in [s.id for s in sensors]:
                target_id = sensor_input

        if target_id:
            self.sensor_manager.remove_sensor(target_id)
            print(f"✓ Sensor '{target_id}' removido exitosamente.")
            
            # Listar sensores restantes
            remaining = self.sensor_manager.list_sensors()
            if remaining:
                print("\n--- LISTA ACTUALIZADA DE SENSORES REGISTRADOS ---")
                rem_rows = [[i, s.id, s.name, s.type, s.protocol, s.ip, s.location] for i, s in enumerate(remaining, 1)]
                print(format_table(headers, rem_rows))
            else:
                print("No quedan sensores registrados en la configuración.")
            print()
        else:
            print(f"❌ No se encontró ningún sensor correspondiente a '{sensor_input}'.\n")

    async def check_system_status(self) -> None:
        """Opción 3: Verificar Estado del Sistema."""
        sensors = self.sensor_manager.list_sensors()
        headers = ["ID", "Nombre", "Tipo", "Protocolo", "IP / Host", "Station ID", "Estado"]
        rows = []
        recent = self.collector_service.recent_measurements

        for s in sensors:
            status = "✓ ACTIVO"
            if s.id in recent:
                m = recent[s.id]
                if m.quality != "ok":
                    status = f"✗ {m.quality.upper()}"
            rows.append([s.id, s.name, s.type, s.protocol, s.ip, s.station_id or "-", status])

        print("\n" + "=" * 70)
        print("          VERIFICACIÓN DE ESTADO DEL SISTEMA Y SENSORES")
        print("=" * 70)
        print(format_table(headers, rows))

        print("\n--- BASE DE DATOS Y ALMACENAMIENTO ---")
        mongo_uri = settings.mongo_uri or "No configurado"
        mongo_ok = MongoDBStorage.validate_connection(mongo_uri) if settings.mongo_uri else False
        mongo_status = "✓ CONECTADO" if mongo_ok else "✗ NO CONECTADO"
        print(f"  • MongoDB Atlas/Local : {mongo_status} (DB: {settings.mongo_db}, Tabla: {settings.mongo_collection}, Intervalo: {settings.mongo_save_interval_min}m)")
        print(f"  • SQLite Buffer Local : ✓ OK ({settings.sqlite_path})")
        print(f"  • Archivo CSV Storage : ✓ OK ({settings.csv_path})")
        print("=" * 70 + "\n")

    async def test_connectivity(self) -> None:
        """Opción 4: Probar Conectividad Sensores y Base de Datos."""
        print("\n--- PRUEBA DE CONECTIVIDAD DE SENSORES Y SERVICIOS ---")
        sensors = self.sensor_manager.list_sensors()
        if not sensors:
            print("No hay sensores registrados.")
        else:
            for s in sensors:
                if s.protocol == "http":
                    print(f"\n▶ Diagnosticando sensor AirLink [{s.id}] (IP: {s.ip}):")
                    icmp_ok = await NetworkService.ping_icmp(s.ip)
                    icmp_str = "✓ PING ICMP EXITOSO" if icmp_ok else "✗ PING ICMP SIN RESPUESTA"
                    print(f"  • {icmp_str}")

                    http_ok = await NetworkService.test_http_endpoint(s.ip)
                    http_str = "✓ SERVICIO HTTP LOCAL RESPONDIENDO (Puerto 80/8002 OK)" if http_ok else "✗ SERVICIO HTTP LOCAL SIN RESPUESTA"
                    print(f"  • {http_str}")

                    if not http_ok and settings.davis_api_key and settings.davis_api_secret:
                        print("  🔍 Intentando autodescubrir IP local desde la nube WeatherLink...")
                        discovered_ip = await NetworkService.discover_airlink_ip(settings.davis_api_key, settings.davis_api_secret)
                        if discovered_ip and discovered_ip != s.ip:
                            print(f"  💡 Se encontró una nueva IP reportada en la nube: {discovered_ip}")

                    if s.station_id:
                        print(f"  • Registrado para respaldo en nube WeatherLink (Station ID: {s.station_id})")
                else:
                    ok = await NetworkService.test_mqtt_connection(s.broker or s.ip)
                    status_str = "✓ BROKER MQTT OK" if ok else "✗ SIN RESPUESTA BROKER"
                    print(f"  • Sensor MQTT [{s.id}] ({s.ip}): {status_str}")

        print("\n--- PRUEBA DE CONEXIÓN A MONGODB ---")
        current_uri = settings.mongo_uri or ""
        if current_uri:
            display_uri = current_uri
            if "@" in display_uri and "://" in display_uri:
                proto, rest = display_uri.split("://", 1)
                creds_host = rest.split("@", 1)
                display_uri = f"{proto}://*****:*****@{creds_host[1]}"
            print(f"  Probando MongoDB en URI: {display_uri[:45]}...")
            ok, summary, diag = await asyncio.to_thread(MongoDBStorage.validate_connection_detailed, current_uri)
            if ok:
                print("  ✓ Conexión exitosa a MongoDB.")
            else:
                print(f"  ❌ Falló la conexión a MongoDB: {summary}")
                print("\n" + diag + "\n")
                change = await self._async_input("  ¿Desea abrir el menú de configuración y diagnóstico de MongoDB (Opción 8)? [s/N]: ")
                if change.strip().lower() == 's':
                    await self.configure_mongodb_wizard()
        else:
            print("  ⚠️ URI de MongoDB no configurada.")
            change = await self._async_input("  ¿Desea configurar MongoDB ahora? [s/N]: ")
            if change.strip().lower() == 's':
                await self.configure_mongodb_wizard()
        print()

    async def take_current_reading(self) -> None:
        """Opción 5: Tomar Lectura Actual bajo demanda."""
        sensors = self.sensor_manager.list_sensors()
        if not sensors:
            print("\n❌ No hay sensores registrados para leer.\n")
            return

        print("\n" + "=" * 90)
        print("         ⚡ TOMANDO LECTURA ACTUAL INSTANTÁNEA...")
        print("=" * 90)
        print("\nSENSORES REGISTRADOS:")
        for idx, s in enumerate(sensors, 1):
            print(f"  {idx}. [{s.id}] {s.name} ({s.location}) - IP/Host: {s.ip}")
        print("  0. Leer TODOS los sensores")

        choice_str = await self._async_input("\nSeleccione el número de sensor que desea leer [0]: ")
        choice_str = choice_str.strip()

        adapters_to_read = []
        all_adapters = self.sensor_manager.get_all_adapters()

        if choice_str.isdigit() and choice_str != "0":
            idx = int(choice_str) - 1
            if 0 <= idx < len(sensors):
                target_sensor = sensors[idx]
                adapters_to_read = [a for a in all_adapters if a.config.id == target_sensor.id]
            else:
                print("❌ Selección inválida. Leyendo todos los sensores por defecto.")
                adapters_to_read = all_adapters
        else:
            adapters_to_read = all_adapters

        if not adapters_to_read:
            print("❌ No hay adaptadores activos para la selección.")
            return

        tasks = [self.collector_service._read_single_sensor(adapter) for adapter in adapters_to_read]
        await asyncio.gather(*tasks, return_exceptions=True)

        recent = self.collector_service.recent_measurements
        print()
        for adapter in adapters_to_read:
            sid = adapter.config.id
            if sid in recent:
                m = recent[sid]
                ts_str = m.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                metrics = m.metrics or {}

                if m.quality in ["ok", "davis_fallback"]:
                    raw_temp = metrics.get('temp')
                    if isinstance(raw_temp, (int, float)):
                        temp_c_str = f"{round((raw_temp - 32) * 5 / 9, 1)}°C"
                    else:
                        temp_c_str = f"{raw_temp}°C" if raw_temp is not None else "N/D"

                    hum = f"{metrics.get('hum')}%" if metrics.get('hum') is not None else "N/D"
                    pm1 = f"{metrics.get('pm_1_last')} ug/m3" if metrics.get('pm_1_last') is not None else "N/D"
                    pm25 = f"{metrics.get('pm_2p5_last')} ug/m3" if metrics.get('pm_2p5_last') is not None else "N/D"
                    pm10 = f"{metrics.get('pm_10_last')} ug/m3" if metrics.get('pm_10_last') is not None else "N/D"

                    print(f"✓ Timestamp: {ts_str} | Sensor: {sid} | Temp: {temp_c_str} | Hum: {hum} | PM1.0: {pm1} | PM2.5: {pm25} | PM10: {pm10}")
                else:
                    print(f"✗ Timestamp: {ts_str} | Sensor: {sid} | [sin conexión]")
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"✗ Timestamp: {now_str} | Sensor: {sid} | [sin conexión]")

        print("=" * 90 + "\n")

    async def start_monitoring_screen(self) -> None:
        """Opción 6: Iniciar Monitoreo Activo."""
        sensors = self.sensor_manager.list_sensors()
        if not sensors:
            print("\n❌ No hay sensores registrados para monitorear.\n")
            return

        print("\n--- CONFIGURACIÓN DE MONITOREO ACTIVO ---")
        interval_str = await self._async_input("Ingrese la frecuencia de recolección en minutos (ej: 1, 2, 5) [1]: ")
        interval_min = int(interval_str.strip()) if interval_str.strip().isdigit() and int(interval_str.strip()) > 0 else 1
        
        self.collector_service.collect_interval_min = interval_min

        print("\n" + "=" * 90)
        print(f"     ▶ INICIANDO MONITOREO ACTIVO EN TIEMPO REAL (Cada {interval_min} minuto(s))")
        print("     Presione [ENTER] o [Ctrl + C] en cualquier momento para detener y regresar al menú.")
        print("=" * 90 + "\n")

        await self.collector_service.start()

        stop_task = asyncio.create_task(self._async_input(""))
        try:
            while not stop_task.done():
                await asyncio.sleep(0.5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            if not stop_task.done():
                stop_task.cancel()
            print("\n⏹️ Deteniendo recolección de datos...")
            await self.collector_service.stop()
            print("✓ Recolección detenida. Regresando al menú principal...\n")


    async def export_data(self) -> None:
        """Opción 7: Generar Archivo de Reporte (CSV)."""
        print("\n--- GENERAR ARCHIVO DE REPORTE (CSV) ---")
        days_str = await self._async_input("Ingrese rango de días hacia atrás a exportar [1]: ")
        days = int(days_str.strip()) if days_str.strip().isdigit() else 1
        
        start_dt = datetime.now() - timedelta(days=days)
        end_dt = datetime.now()

        df = await self.csv_storage.export_range(start_dt, end_dt)
        out_file = f"data/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        if hasattr(df, "to_csv"):
            df.to_csv(out_file, index=False)
            print(f"✓ {len(df)} registros exportados a {out_file}\n")
        else:
            print("❌ No se pudo exportar (Pandas no instalado).\n")

    async def configure_mongodb_wizard(self) -> None:
        """Opción 8: Configurar Base de Datos MongoDB, Diagnóstico e IP."""
        while True:
            print("\n" + "=" * 70)
            print("         🗄️ CONFIGURACIÓN Y DIAGNÓSTICO DE MONGODB")
            print("=" * 70)
            current_uri = settings.mongo_uri or "No configurado"
            
            display_uri = current_uri
            if "@" in display_uri and "://" in display_uri:
                proto, rest = display_uri.split("://", 1)
                creds_host = rest.split("@", 1)
                display_uri = f"{proto}://*****:*****@{creds_host[1]}"

            mode_str = "Horas Cerradas" if getattr(settings, "mongo_sync_mode", "closed") == "closed" else "Intervalo Abierto"
            print(f" Estado Actual : {status_str}")
            print(f" URI Actual    : {display_uri}")
            print(f" Base de Datos : {settings.mongo_db}")
            print(f" Colección     : {settings.mongo_collection}")
            print(f" Modo Guardado : {mode_str}")
            print(f" Intervalo     : {settings.mongo_save_interval_min} minutos")
            print("=" * 70)

            print("\n OPCIONES DE CONFIGURACIÓN Y DIAGNÓSTICO:")
            print(" 1. Ingresar Usuario y Contraseña (MongoDB Atlas con Auto URL-encoding)")
            print(" 2. Ingresar URI completa de MongoDB (Local o Atlas)")
            print(" 3. Probar conexión a MongoDB y ver Diagnóstico Detallado")
            print(" 4. Diagnóstico de Red e IP para Raspberry Pi (Resolver DNS / IP Pública Atlas)")
            print(" 5. Cambiar Plantilla URI de MongoDB (Cluster URL)")
            print(" 6. Configurar Nombre de Base de Datos y Colección")
            print(" 7. Configurar Modo e Intervalo de Guardado en MongoDB (Horas cerradas vs Abierto)")
            print(" 8. Volver al menú principal")

            sub_choice = await self._async_input("\nSeleccione una opción [1-8]: ")
            sub_choice = sub_choice.strip()

            if sub_choice == "1":
                print("\n--- INGRESO DE CREDENCIALES DE MONGODB ATLAS ---")
                user = await self._async_input("Ingrese Usuario de MongoDB Atlas: ")
                pwd = await self._async_input("Ingrese Contraseña de MongoDB Atlas: ")
                user, pwd = user.strip(), pwd.strip()
                if not user or not pwd:
                    print("❌ Usuario y contraseña no pueden estar vacíos.\n")
                    continue

                safe_user = urllib.parse.quote_plus(user)
                safe_pwd = urllib.parse.quote_plus(pwd)

                template = settings.mongo_uri_template or "mongodb+srv://<USER>:<PASSWORD>@tests.xqm2ykn.mongodb.net/air_quality?retryWrites=true&w=majority&appName=Tests"
                target_uri = template.replace("<USER>", safe_user).replace("<PASSWORD>", safe_pwd)

                print("\n🔍 Validando conexión a MongoDB...")
                ok, summary, diag = await asyncio.to_thread(MongoDBStorage.validate_connection_detailed, target_uri)
                if ok:
                    save_env_variable("MONGO_URI", target_uri)
                    settings.mongo_uri = target_uri
                    if self.mongo_storage:
                        self.mongo_storage.uri = target_uri
                    print("✓ ¡Conexión exitosa a MongoDB! Configuración guardada en .env\n")
                else:
                    print(f"\n❌ Falló la conexión a MongoDB: {summary}\n")
                    print(diag)
                    print("\n💾 Si estás seguro de tus credenciales y deseas guardarlas de todos modos para resolver el DNS/IP después:")
                    save_opt = await self._async_input("  ¿Deseas guardar esta URI en .env de todos modos? [s/N]: ")
                    if save_opt.strip().lower() == 's':
                        save_env_variable("MONGO_URI", target_uri)
                        settings.mongo_uri = target_uri
                        if self.mongo_storage:
                            self.mongo_storage.uri = target_uri
                        print("✓ URI guardada en .env\n")

            elif sub_choice == "2":
                print("\n--- INGRESO DE URI COMPLETA ---")
                print("Ejemplo Atlas SRV : mongodb+srv://usuario:password@cluster.xqm2ykn.mongodb.net/air_quality")
                print("Ejemplo Directo   : mongodb://usuario:password@node1.mongodb.net:27017,node2.mongodb.net:27017/air_quality?ssl=true")
                print("Ejemplo Local     : mongodb://localhost:27017")
                target_uri = await self._async_input("Ingrese URI completa de MongoDB: ")
                target_uri = target_uri.strip()
                if target_uri:
                    print("\n🔍 Validando nueva URI...")
                    ok, summary, diag = await asyncio.to_thread(MongoDBStorage.validate_connection_detailed, target_uri)
                    if ok:
                        save_env_variable("MONGO_URI", target_uri)
                        settings.mongo_uri = target_uri
                        if self.mongo_storage:
                            self.mongo_storage.uri = target_uri
                        print("✓ ¡Conexión exitosa a MongoDB! Configuración guardada en .env\n")
                    else:
                        print(f"\n❌ Falló la conexión con la URI ingresada: {summary}\n")
                        print(diag)
                        save_opt = await self._async_input("\n¿Deseas guardar esta URI en .env de todos modos? [s/N]: ")
                        if save_opt.strip().lower() == 's':
                            save_env_variable("MONGO_URI", target_uri)
                            settings.mongo_uri = target_uri
                            if self.mongo_storage:
                                self.mongo_storage.uri = target_uri
                            print("✓ URI guardada en .env\n")

            elif sub_choice == "3":
                print("\n🔍 Probando conexión a MongoDB...")
                if not current_uri or current_uri == "No configurado":
                    print("⚠️ URI de MongoDB no configurada. Utilice la opción 1 o 2 primero.\n")
                else:
                    ok, summary, diag = await asyncio.to_thread(MongoDBStorage.validate_connection_detailed, current_uri)
                    if ok:
                        print(f"✓ ¡Conexión EXITOSA a MongoDB! (DB: {settings.mongo_db}, Colección: {settings.mongo_collection})\n")
                    else:
                        print(f"\n❌ RESULTADO DE LA PRUEBA: {summary}\n")
                        print(diag)
                        print()

            elif sub_choice == "4":
                print("\n--- DIAGNÓSTICO DE RED E IP PARA RASPBERRY PI ---")
                local_ip = get_local_ip()
                public_ip = await NetworkService.get_public_ip()
                print(f"  • IP Local Raspberry Pi  : {local_ip}")
                print(f"  • IP Pública Actual      : {public_ip or 'No se pudo obtener (verificar conexión a Internet)'}")
                if public_ip:
                    print(f"    👉 Copia esta IP ({public_ip}) y agrégala en MongoDB Atlas -> Network Access.")
                
                print("\n  • Probando resolución DNS general (google.com)...")
                dns_ok, dns_msg = await NetworkService.test_dns_resolution("google.com")
                print(f"    {dns_msg}")

                print("  • Probando resolución DNS para MongoDB Atlas (tests.xqm2ykn.mongodb.net)...")
                atlas_ok, atlas_msg = await NetworkService.test_dns_resolution("tests.xqm2ykn.mongodb.net")
                print(f"    {atlas_msg}")

                if not dns_ok or not atlas_ok:
                    print("\n⚠️ DETECTADO PROBLEMA DE DNS EN LA RASPBERRY PI:")
                    print("   Tu Raspberry Pi no está resolviendo nombres de dominio correctamente.")
                    print("   Para solucionar 'The resolution lifetime expired...', ejecuta en la consola de la Raspberry Pi:")
                    print("     sudo nano /etc/resolv.conf")
                    print("   Y añade como primera línea:")
                    print("     nameserver 8.8.8.8")

            elif sub_choice == "5":
                print("\n--- CAMBIAR PLANTILLA DE URI MONGODB ---")
                print(f"Plantilla actual: {settings.mongo_uri_template}")
                new_tpl = await self._async_input("Ingrese nueva plantilla (debe incluir <USER> y <PASSWORD>): ")
                new_tpl = new_tpl.strip()
                if new_tpl and "<USER>" in new_tpl and "<PASSWORD>" in new_tpl:
                    save_env_variable("MONGO_URI_TEMPLATE", new_tpl)
                    settings.mongo_uri_template = new_tpl
                    print("✓ Plantilla de URI actualizada y guardada en .env\n")
                else:
                    print("❌ Plantilla inválida. Debe contener las marcas <USER> y <PASSWORD>.\n")

            elif sub_choice == "6":
                print("\n--- BASE DE DATOS Y COLECCIÓN ---")
                new_db = await self._async_input(f"Nombre de Base de Datos [{settings.mongo_db}]: ")
                new_coll = await self._async_input(f"Nombre de Colección [{settings.mongo_collection}]: ")
                if new_db.strip():
                    save_env_variable("MONGO_DB", new_db.strip())
                    settings.mongo_db = new_db.strip()
                    if self.mongo_storage:
                        self.mongo_storage.db_name = new_db.strip()
                if new_coll.strip():
                    save_env_variable("MONGO_COLLECTION", new_coll.strip())
                    settings.mongo_collection = new_coll.strip()
                    if self.mongo_storage:
                        self.mongo_storage.collection_name = new_coll.strip()
                print("✓ Configuración de BD/Colección actualizada en .env\n")

            elif sub_choice == "7":
                print("\n--- CONFIGURACIÓN DE INTERVALO Y MODO DE REGISTRO EN MONGODB ---")
                print("Seleccione la modalidad de registro:")
                print(" 1. Horas cerradas (Recomendado: fija minutos exactos :00, :15, :30, etc.)")
                print(" 2. Intervalo abierto (Sincroniza continuamente a intervalos de N minutos desde que inicia)")
                
                mode_choice = await self._async_input("Seleccione modalidad [1]: ")
                mode_choice = mode_choice.strip()
                selected_mode = "open" if mode_choice == "2" else "closed"

                if selected_mode == "closed":
                    print("\nSeleccione el intervalo a horas cerradas:")
                    print(" 1. Cada 10 minutos (:00, :10, :20, :30, :40, :50)")
                    print(" 2. Cada 15 minutos (:00, :15, :30, :45) [Por defecto]")
                    print(" 3. Cada 20 minutos (:00, :20, :40)")
                    print(" 4. Cada 30 minutos (:00, :30)")
                    print(" 5. Cada 60 minutos (:00)")
                    print(" 6. Otro intervalo personalizado")

                    int_sel = await self._async_input("Seleccione opción [2]: ")
                    int_sel = int_sel.strip()
                    interval_mapping = {"1": 10, "2": 15, "3": 20, "4": 30, "5": 60}
                    
                    if int_sel in interval_mapping:
                        selected_interval = interval_mapping[int_sel]
                    elif int_sel == "6":
                        custom_val = await self._async_input("Ingrese los minutos para horas cerradas (ej: 5, 10, 15): ")
                        selected_interval = int(custom_val.strip()) if custom_val.strip().isdigit() and int(custom_val.strip()) > 0 else 15
                    else:
                        selected_interval = 15
                else:
                    custom_val = await self._async_input("Ingrese la frecuencia en minutos para intervalo abierto [15]: ")
                    selected_interval = int(custom_val.strip()) if custom_val.strip().isdigit() and int(custom_val.strip()) > 0 else 15

                save_env_variable("MONGO_SYNC_MODE", selected_mode)
                save_env_variable("MONGO_SAVE_INTERVAL_MIN", str(selected_interval))
                settings.mongo_sync_mode = selected_mode
                settings.mongo_save_interval_min = selected_interval
                
                if self.collector_service:
                    self.collector_service.sync_mode = selected_mode
                    self.collector_service.sync_interval_min = selected_interval

                label_mode = "Horas cerradas" if selected_mode == "closed" else "Intervalo abierto"
                print(f"\n✓ Modalidad configurada: '{label_mode}' cada {selected_interval} minutos. Guardado en .env\n")

            elif sub_choice == "8":
                break

            else:
                print("❌ Opción inválida. Ingrese un número entre 1 y 8.")

    async def show_main_menu(self) -> None:
        menu_text = """
╔════════════════════════════════════════════════════════════════╗
║           SISTEMA DE MONITOREO AMBIENTAL - CAMPUS             ║
╚════════════════════════════════════════════════════════════════╝

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
"""
        print(menu_text)
        while True:
            try:
                choice = await self._async_input("\nSeleccione una opción [1-9]: ")
                choice = choice.strip()
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n\nSaliendo de forma segura...")
                await self.collector_service.shutdown()
                break

            if choice == "1":
                await self.add_sensor_wizard()
                print(menu_text)
            elif choice == "2":
                await self.remove_sensor()
                print(menu_text)
            elif choice == "3":
                await self.check_system_status()
                print(menu_text)
            elif choice == "4":
                await self.test_connectivity()
                print(menu_text)
            elif choice == "5":
                await self.take_current_reading()
                print(menu_text)
            elif choice == "6":
                await self.start_monitoring_screen()
                print(menu_text)
            elif choice == "7":
                await self.export_data()
                print(menu_text)
            elif choice == "8":
                await self.configure_mongodb_wizard()
                print(menu_text)
            elif choice == "9":
                print("\nCerrando el sistema de forma segura...")
                await self.collector_service.shutdown()
                print("✓ Sistema cerrado correctamente.")
                break
            else:
                print("❌ Opción inválida. Ingrese un número entre 1 y 9.")


