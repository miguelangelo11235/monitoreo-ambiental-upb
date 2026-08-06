import sys
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from models.sensor import SensorConfig
from services.sensor_manager import SensorManager
from services.collector_service import CollectorService
from services.network_service import NetworkService
from adapters.fallback_handler import FallbackHandler
from storage.sqlite_buffer import SQLiteBuffer
from storage.csv_storage import CSVStorage
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
    """Menú interactivo CLI simplificado a 8 opciones principales."""

    def __init__(
        self,
        collector_service: CollectorService,
        sensor_manager: SensorManager,
        sqlite_buffer: SQLiteBuffer,
        csv_storage: CSVStorage
    ):
        self.collector_service = collector_service
        self.sensor_manager = sensor_manager
        self.sqlite_buffer = sqlite_buffer
        self.csv_storage = csv_storage
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
        sensor_id = await self._async_input("\nIngrese ID del sensor a remover: ")
        sensor_id = sensor_id.strip()
        if sensor_id in [s.id for s in self.sensor_manager.list_sensors()]:
            self.sensor_manager.remove_sensor(sensor_id)
            print(f"✓ Sensor '{sensor_id}' removido.\n")
        else:
            print(f"❌ No se encontró ningún sensor con ID '{sensor_id}'.\n")

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
        print("=" * 70 + "\n")

    async def test_connectivity(self) -> None:
        """Opción 4: Probar Conectividad Sensores."""
        print("\n--- PRUEBA DE CONECTIVIDAD DE SENSORES ---")
        sensors = self.sensor_manager.list_sensors()
        if not sensors:
            print("No hay sensores registrados.")
            return

        for s in sensors:
            if s.protocol == "http":
                ok = await NetworkService.test_http_endpoint(f"http://{s.ip}:8002/v1/current_conditions")
                status_str = "✓ RED LOCAL OK" if ok else "✗ SIN RESPUESTA LOCAL"
                if s.station_id:
                    status_str += f" (Station ID Cloud: {s.station_id})"
            else:
                ok = await NetworkService.test_mqtt_connection(s.broker or s.ip)
                status_str = "✓ BROKER MQTT OK" if ok else "✗ SIN RESPUESTA BROKER"
            print(f"  • [{s.id}] ({s.ip}): {status_str}")
        print()

    async def take_current_reading(self) -> None:
        """Opción 5: Tomar Lectura Actual bajo demanda."""
        print("\n" + "=" * 65)
        print("         ⚡ TOMANDO LECTURA ACTUAL INSTANTÁNEA...")
        print("=" * 65)

        adapters = self.sensor_manager.get_all_adapters()
        if not adapters:
            print("❌ No hay sensores activos para leer.")
            return

        tasks = [self.collector_service._read_single_sensor(adapter) for adapter in adapters]
        await asyncio.gather(*tasks, return_exceptions=True)

        recent = self.collector_service.recent_measurements
        now_str = datetime.now().strftime("%H:%M:%S")

        print(f"\nRESULTADOS DE LA LECTURA [{now_str}]:")
        for sid, m in recent.items():
            status_symbol = "✓" if m.quality == "ok" else "✗"
            print(f"\n▶ {status_symbol} Sensor '{sid}' ({m.location}) - Estado: {m.quality}")
            if m.metrics:
                for metric, val in m.metrics.items():
                    print(f"   • {metric}: {val}")
            else:
                print("   • Sin datos recibidos / Timeout")
        print("\n" + "=" * 65 + "\n")

    async def start_monitoring_screen(self) -> None:
        """Opción 6: Iniciar Monitoreo Activo."""
        print("\n" + "=" * 65)
        print("     ▶ INICIANDO MONITOREO ACTIVO EN TIEMPO REAL")
        print("     Presione [Ctrl + C] en cualquier momento para detener")
        print("     las lecturas y regresar al menú principal.")
        print("=" * 65 + "\n")

        await self.collector_service.start()

        try:
            while True:
                recent = self.collector_service.recent_measurements
                now_str = datetime.now().strftime("%H:%M:%S")
                print(f"--- ESTADO DE LECTURA [{now_str}] ---")

                if not recent:
                    print("  [Recolectando datos de los sensores activos, espere...]")
                else:
                    for sid, m in recent.items():
                        status_symbol = "✓" if m.quality == "ok" else "✗"
                        print(f"  {status_symbol} Sensor '{sid}' ({m.location}) -> Estado: {m.quality}")
                        if m.metrics:
                            metric_strs = [f"{k}: {v}" for k, v in m.metrics.items()]
                            print(f"     Metrics: {', '.join(metric_strs)}")
                        else:
                            print("     Metrics: Sin datos / Timeout")

                print("  (Monitoreando... presione Ctrl+C para detener y volver al menú)")
                await asyncio.sleep(5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n\n⏹️ Deteniendo recolección de datos...")
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
 8. Salir
"""
        print(menu_text)
        while True:
            try:
                choice = await self._async_input("\nSeleccione una opción [1-8]: ")
                choice = choice.strip()
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n\nSaliendo de forma segura...")
                await self.collector_service.shutdown()
                break

            if choice == "1":
                await self.add_sensor_wizard()
            elif choice == "2":
                await self.remove_sensor()
            elif choice == "3":
                await self.check_system_status()
            elif choice == "4":
                await self.test_connectivity()
            elif choice == "5":
                await self.take_current_reading()
            elif choice == "6":
                await self.start_monitoring_screen()
                print(menu_text)
            elif choice == "7":
                await self.export_data()
            elif choice == "8":
                print("\nCerrando el sistema de forma segura...")
                await self.collector_service.shutdown()
                print("✓ Sistema cerrado correctamente.")
                break
            else:
                print("❌ Opción inválida. Ingrese un número entre 1 y 8.")
