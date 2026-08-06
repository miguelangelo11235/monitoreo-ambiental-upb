import sys
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from models.sensor import SensorConfig
from services.sensor_manager import SensorManager
from services.collector_service import CollectorService
from services.network_service import NetworkService
from storage.sqlite_buffer import SQLiteBuffer
from storage.csv_storage import CSVStorage

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
    """Menú interactivo CLI para administración y monitoreo en consola."""

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

    async def _async_input(self, prompt: str) -> str:
        return await asyncio.to_thread(input, prompt)

    async def list_sensors(self) -> None:
        sensors = self.sensor_manager.list_sensors()
        headers = ["ID", "Nombre", "Tipo", "Protocolo", "Ubicación", "Estado"]
        rows = []
        recent = self.collector_service.recent_measurements

        for s in sensors:
            status = "✓ OK"
            if s.id in recent:
                m = recent[s.id]
                if m.quality != "ok":
                    status = f"✗ {m.quality.upper()}"
            rows.append([s.id, s.name, s.type, s.protocol, s.location, status])

        print("\n" + "=" * 60)
        print("                SENSORES REGISTRADOS")
        print("=" * 60)
        print(format_table(headers, rows))
        print("=" * 60 + "\n")

    async def add_sensor_wizard(self) -> None:
        print("\n--- ASISTENTE PARA AGREGAR SENSOR ---")
        sensor_type = await self._async_input("Tipo de sensor (airlink/mqtt/esp32): ")
        sensor_type = sensor_type.strip().lower()
        if sensor_type not in ["airlink", "mqtt", "esp32"]:
            print("❌ Tipo de sensor no soportado.")
            return

        sensor_id = await self._async_input("ID único (ej: airlink_02, esp32_01): ")
        name = await self._async_input("Nombre descriptivo: ")
        location = await self._async_input("Ubicación física: ")
        ip = await self._async_input("IP o Broker (ej: 192.168.1.100 / 127.0.0.1): ")

        topic = None
        protocol = "http"
        if sensor_type in ["mqtt", "esp32"]:
            protocol = "mqtt"
            topic = await self._async_input("Topic MQTT (ej: campus/lab_a/temperature): ")

        timeout_str = await self._async_input("Timeout en segundos [5]: ")
        timeout_seconds = int(timeout_str.strip()) if timeout_str.strip().isdigit() else 5

        print("\nTesteando conexión con el sensor...")
        online = False
        if protocol == "http":
            url = f"http://{ip}:8002/v1/current_conditions"
            online = await NetworkService.test_http_endpoint(url, timeout=2.0)
        else:
            online = await NetworkService.test_mqtt_connection(ip, timeout=2.0)

        if online:
            print("✓ Conexión exitosa con el dispositivo.")
        else:
            print("⚠️ Advertencia: No se pudo verificar conectividad previa. Se guardará de todos modos.")

        config = SensorConfig(
            id=sensor_id.strip(),
            name=name.strip(),
            type=sensor_type,
            protocol=protocol,
            ip=ip.strip(),
            broker=ip.strip() if protocol == "mqtt" else "127.0.0.1",
            topic=topic.strip() if topic else None,
            location=location.strip(),
            enabled=True,
            timeout_seconds=timeout_seconds
        )

        self.sensor_manager.add_sensor(config)
        print(f"✓ Sensor '{sensor_id}' agregado exitosamente a sensors_config.json\n")

    async def remove_sensor(self) -> None:
        sensor_id = await self._async_input("\nIngrese ID del sensor a remover: ")
        sensor_id = sensor_id.strip()
        if sensor_id in [s.id for s in self.sensor_manager.list_sensors()]:
            self.sensor_manager.remove_sensor(sensor_id)
            print(f"✓ Sensor '{sensor_id}' removido.\n")
        else:
            print(f"❌ No se encontró ningún sensor con ID '{sensor_id}'.\n")

    async def view_measurements(self) -> None:
        recent = self.collector_service.recent_measurements
        print("\n" + "=" * 60)
        print("              ÚLTIMAS MEDICIONES RECOLECTADAS")
        print("=" * 60)
        if not recent:
            print("Aún no se han capturado lecturas o el bucle está iniciando...")
        else:
            for sid, m in recent.items():
                print(f"\n▶ {sid} ({m.location}) [{m.timestamp.strftime('%H:%M:%S')}] - Estado: {m.quality}")
                if m.metrics:
                    for metric, val in m.metrics.items():
                        print(f"   • {metric}: {val}")
                else:
                    print("   • Sin datos recibidos")
        print("=" * 60 + "\n")

    async def export_data(self) -> None:
        print("\n--- EXPORTAR DATOS A CSV ---")
        days_str = await self._async_input("Ingrese rango de días hacia atrás a exportar [1]: ")
        days = int(days_str.strip()) if days_str.strip().isdigit() else 1
        
        start_dt = datetime.now() - timedelta(days=days)
        end_dt = datetime.now()

        df = await self.csv_storage.export_range(start_dt, end_dt)
        out_file = f"data/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(out_file, index=False)
        print(f"✓ {len(df)} registros exportados a {out_file}\n")

    async def test_connectivity(self) -> None:
        print("\n--- PRUEBA DE CONECTIVIDAD DE SENSORES ---")
        sensors = self.sensor_manager.list_sensors()
        for s in sensors:
            if s.protocol == "http":
                ok = await NetworkService.test_http_endpoint(f"http://{s.ip}:8002/v1/current_conditions")
            else:
                ok = await NetworkService.test_mqtt_connection(s.broker or s.ip)
            status_str = "✓ RESPUNDE" if ok else "✗ SIN RESPUESTA"
            print(f"  • [{s.id}] ({s.ip}): {status_str}")
        print()

    async def view_logs(self) -> None:
        print("\n--- ÚLTIMOS EVENTOS Y ERRORES (SQLITE) ---")
        events = await self.sqlite_buffer.read_events(limit=15)
        if not events:
            print("No hay eventos registrados.")
        else:
            for e in events:
                print(f"[{e['timestamp']}] [{e['event_type']}] Sensor: {e['sensor_id'] or 'N/A'} - {e['message']}")
        print()

    async def show_main_menu(self) -> None:
        title = """
╔════════════════════════════════════════════════════════════════╗
║           SISTEMA DE MONITOREO AMBIENTAL - CAMPUS             ║
╚════════════════════════════════════════════════════════════════╝
"""
        print(title)
        while True:
            prompt = "\n>>> Menú: [L]istar [A]gregar [R]emover [V]er [E]xportar [T]est [E]ventos [Q]uit: "
            choice = await self._async_input(prompt)
            choice = choice.strip().upper()

            if choice == "L":
                await self.list_sensors()
            elif choice == "A":
                await self.add_sensor_wizard()
            elif choice == "R":
                await self.remove_sensor()
            elif choice == "V":
                await self.view_measurements()
            elif choice == "E":
                await self.export_data()
            elif choice == "T":
                await self.test_connectivity()
            elif choice in ["EVENTOS", "EV"]:
                await self.view_logs()
            elif choice == "Q":
                print("Cerrando interfaz de consola...")
                break
            else:
                print("Opción inválida. Intente de nuevo.")
