"""Terminal UI: a live monitor tab and an administration tab."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, Select, Static, Switch, TabbedContent, TabPane,
)

from .db import Device, Inventory
from .pinger import DOWN, PENDING, UP, Monitor

ALL_ZONES = -1


def _fmt_ms(value: float | None) -> str:
    return f"{value:.1f} ms" if value is not None else "-"


def _fmt_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    fmt = "%H:%M:%S" if value.date() == datetime.now().date() else "%d/%m %H:%M"
    return value.strftime(fmt)


# --- modal dialogs ---------------------------------------------------------


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "dismiss(False)", "Cancelar")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.message, classes="dialog-text")
            with Horizontal(classes="buttons"):
                yield Button("Eliminar", variant="error", id="yes")
                yield Button("Cancelar", id="no")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class ZoneForm(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "Cancelar")]

    def __init__(self, title: str, name: str = ""):
        super().__init__()
        self.form_title, self.initial = title, name

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.form_title, classes="dialog-title")
            yield Label("Nombre de la zona")
            yield Input(self.initial, id="name")
            yield Label("", id="error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Guardar", variant="primary", id="save")
                yield Button("Cancelar", id="cancel")

    @on(Input.Submitted)
    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.query_one("#error", Label).update("El nombre no puede estar vacío.")
            return
        self.dismiss(name)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class DeviceForm(ModalScreen[dict | None]):
    """Add/edit a device. Returns the field values; the caller validates and saves."""

    BINDINGS = [("escape", "dismiss(None)", "Cancelar")]

    def __init__(self, title: str, zones: list[tuple[str, int]], zone_id: int, device: Device | None = None,
                 validate=None):
        super().__init__()
        self.form_title, self.zones, self.zone_id, self.device = title, zones, zone_id, device
        self.validate = validate

    def compose(self) -> ComposeResult:
        d = self.device
        with Vertical(classes="dialog wide"):
            yield Label(self.form_title, classes="dialog-title")
            yield Label("Zona")
            yield Select(self.zones, value=d.zone_id if d else self.zone_id, allow_blank=False, id="zone")
            yield Label("Grupo (ciclo / sede)")
            yield Input(d.grp if d else "", id="grp")
            yield Label("Código")
            yield Input(d.code if d else "", id="code")
            yield Label("Nombre / cargo")
            yield Input(d.name if d else "", id="name")
            yield Label("IP")
            yield Input(d.ip or "" if d else "", placeholder="192.168.10.55", id="ip")
            yield Label("Notas")
            yield Input(d.notes if d else "", id="notes")
            with Horizontal(classes="switch-row"):
                yield Switch(d.monitored if d else True, id="monitored")
                yield Label("Operativo (se monitorea)")
            yield Label("", id="error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Guardar", variant="primary", id="save")
                yield Button("Cancelar", id="cancel")

    def values(self) -> dict:
        get = lambda i: self.query_one(f"#{i}", Input).value  # noqa: E731
        return {
            "zone_id": self.query_one("#zone", Select).value,
            "grp": get("grp"), "code": get("code"), "name": get("name"),
            "ip": get("ip"), "notes": get("notes"),
            "monitored": self.query_one("#monitored", Switch).value,
        }

    @on(Input.Submitted)
    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        values = self.values()
        if self.validate:
            error = self.validate(values)
            if error:
                self.query_one("#error", Label).update(error)
                return
        self.dismiss(values)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class ImportForm(ModalScreen[tuple[str, bool] | None]):
    BINDINGS = [("escape", "dismiss(None)", "Cancelar")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("Importar Excel de inventario", classes="dialog-title")
            yield Label("Ruta del archivo .xlsx (cada hoja se importa como una zona)")
            yield Input(placeholder=r"C:\Users\...\Downloads\Organización de Red.xlsx", id="path")
            with Horizontal(classes="switch-row"):
                yield Switch(False, id="replace")
                yield Label("Reemplazar todo (borra zonas, equipos e historial actuales)")
            yield Label("", id="error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Importar", variant="primary", id="save")
                yield Button("Cancelar", id="cancel")

    @on(Input.Submitted)
    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        # "Copy as path" in Windows Explorer wraps the path in quotes.
        path = self.query_one("#path", Input).value.strip().strip('"').strip("'")
        if not path:
            self.query_one("#error", Label).update("Indica la ruta del archivo.")
            return
        if not Path(path).is_file():
            self.query_one("#error", Label).update(f"No existe el archivo: {path}")
            return
        self.dismiss((path, self.query_one("#replace", Switch).value))

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class HistoryScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Cerrar"), ("enter", "dismiss", "Cerrar")]

    def __init__(self, device: Device, events):
        super().__init__()
        self.device, self.events = device, events

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            d = self.device
            yield Label(f"Historial: {d.zone_name} / {d.label}  ({d.ip or 'sin IP'})", classes="dialog-title")
            table = DataTable(id="history", cursor_type="row")
            table.add_columns("Fecha y hora", "Cambio")
            for e in self.events:
                state = Text("Cayó", "bold red") if e.state == DOWN else Text("Volvió", "bold green")
                table.add_row(e.ts.strftime("%d/%m/%Y %H:%M:%S"), state)
            if not self.events:
                table.add_row("-", "Sin caídas registradas")
            yield table
            with Horizontal(classes="buttons"):
                yield Button("Cerrar", id="close")

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss()


# --- main app --------------------------------------------------------------


class MonitorApp(App):
    TITLE = "Monitor de red"
    CSS = """
    #filters { height: auto; padding: 0 1; }
    #filters Select { width: 40; }
    #summary { padding: 1 2; width: 1fr; }
    #admin { height: 1fr; }
    #zones-pane { width: 38; border: round $primary; }
    #devices-pane { width: 1fr; border: round $primary; }
    .pane-title { text-style: bold; padding: 0 1; }
    ModalScreen { align: center middle; }
    .dialog { width: 60; height: auto; max-height: 90%; border: thick $primary; background: $surface; padding: 1 2; }
    .dialog.wide { width: 90; }
    .dialog-title { text-style: bold; margin-bottom: 1; }
    .dialog-text { margin-bottom: 1; }
    .error { color: $error; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    .switch-row { height: auto; margin-top: 1; }
    .switch-row Label { padding: 1 1; }
    #history { height: 20; }
    """
    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("f", "toggle_down_only", "Solo caídos"),
        Binding("n", "toggle_all", "Ver no operativos"),
        Binding("h", "history", "Historial"),
        Binding("a", "add", "Agregar"),
        Binding("e", "edit", "Editar"),
        Binding("d,delete", "delete", "Eliminar"),
        Binding("i", "import", "Importar Excel"),
    ]

    def __init__(self, inventory: Inventory, monitor: Monitor):
        super().__init__()
        self.inv = inventory
        self.monitor = monitor
        self.monitor.on_change = self._on_state_change
        self.zone_filter = ALL_ZONES
        self.down_only = False
        self.show_unmonitored = False
        self._devices: list[Device] = []
        self._monitor_rows: list[int] = []

    # --- layout ---

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-monitor", id="tabs"):
            with TabPane("Monitor", id="tab-monitor"):
                with Horizontal(id="filters"):
                    yield Select([("Todas las zonas", ALL_ZONES)], value=ALL_ZONES, allow_blank=False,
                                 id="zone-filter")
                    yield Static("", id="summary")
                yield DataTable(id="monitor", cursor_type="row", zebra_stripes=True)
            with TabPane("Administración", id="tab-admin"):
                with Horizontal(id="admin"):
                    with Vertical(id="zones-pane"):
                        yield Label("Zonas", classes="pane-title")
                        yield DataTable(id="zones", cursor_type="row")
                    with Vertical(id="devices-pane"):
                        yield Label("Equipos", classes="pane-title", id="devices-title")
                        yield DataTable(id="devices", cursor_type="row", zebra_stripes=True)
        yield Footer()

    async def on_mount(self) -> None:
        mon = self.query_one("#monitor", DataTable)
        # Live columns get fixed widths: auto-width would size them from the first
        # refresh ("-") and later values like "timeout" or "123.4 ms" would be cut.
        for key, label, width in [("state", "Estado", 8), ("zone", "Zona", None), ("grp", "Grupo", None),
                                  ("code", "Código", None), ("name", "Nombre", None), ("ip", "IP", 15),
                                  ("resp", "Resp.", 11), ("loss", "Pérd.", 5), ("last", "Última", 9),
                                  ("avg", "Prom.", 9), ("down", "Última caída", 12)]:
            mon.add_column(label, key=key, width=width)
        self.query_one("#zones", DataTable).add_columns("Zona", "Equipos")
        self.query_one("#devices", DataTable).add_columns(
            "Grupo", "Código", "Nombre", "IP", "Operativo", "Notas")
        await self.reload()
        self.set_interval(0.5, self.refresh_monitor)
        if self.inv.is_empty():
            self.notify("La base está vacía. Pulsa i para importar el Excel o ve a Administración "
                        "para crear zonas y equipos.", title="Sin datos", timeout=15)

    # --- data reload ---

    async def reload(self) -> None:
        """Re-read the inventory, refresh every table and resync the pingers."""
        self._devices = self.inv.devices()
        await self.monitor.sync({d.id: d.ip for d in self._devices if d.monitored and d.ip})
        self._load_zone_filter()
        self._load_admin()
        self._rebuild_monitor()

    def _load_zone_filter(self) -> None:
        zones = self.inv.zones()
        if self.zone_filter != ALL_ZONES and not any(z.id == self.zone_filter for z in zones):
            self.zone_filter = ALL_ZONES
        select = self.query_one("#zone-filter", Select)
        with select.prevent(Select.Changed):
            select.set_options([("Todas las zonas", ALL_ZONES)] + [(z.name, z.id) for z in zones])
            select.value = self.zone_filter

    @on(Select.Changed, "#zone-filter")
    def _zone_filter_changed(self, event: Select.Changed) -> None:
        self.zone_filter = event.value
        self._rebuild_monitor()

    def _visible_devices(self) -> list[Device]:
        out = []
        for d in self._devices:
            if self.zone_filter != ALL_ZONES and d.zone_id != self.zone_filter:
                continue
            watched = d.monitored and d.ip
            if not watched and not self.show_unmonitored:
                continue
            if self.down_only and (not watched or self.monitor.status(d.id).state != DOWN):
                continue
            out.append(d)
        return out

    # --- monitor tab ---

    def _rebuild_monitor(self) -> None:
        table = self.query_one("#monitor", DataTable)
        selected = self._monitor_rows[table.cursor_row] if self._monitor_rows and table.cursor_row < len(self._monitor_rows) else None
        table.clear()
        devices = self._visible_devices()
        self._monitor_rows = [d.id for d in devices]
        for d in devices:
            table.add_row(*self._monitor_cells(d), key=str(d.id))
        if selected in self._monitor_rows:
            table.move_cursor(row=self._monitor_rows.index(selected))
        self._update_summary()

    def _monitor_cells(self, d: Device) -> list:
        base = [d.zone_name, d.grp, d.code, d.name, d.ip or "-"]
        if not (d.monitored and d.ip):
            label = "NO OPER." if d.ip else "SIN IP"
            return [Text(label, "dim"), *base, "-", "-", "-", "-", "-"]
        st = self.monitor.status(d.id)
        if st.state == PENDING:
            state = Text("...", "dim")
        elif st.state == DOWN:
            state = Text("CAÍDO", "bold white on red")
        elif st.streak or st.loss:
            state = Text("OK", "bold yellow")
        else:
            state = Text("OK", "bold green")
        last = "timeout" if st.sent and st.last_rtt is None else _fmt_ms(st.last_rtt)
        return [state, *base, f"{st.received}/{st.sent}", f"{st.loss:.0f}%", last,
                _fmt_ms(st.avg_rtt), _fmt_time(st.last_down)]

    def refresh_monitor(self) -> None:
        if self.down_only:
            if [d.id for d in self._visible_devices()] != self._monitor_rows:
                self._rebuild_monitor()
                return
        table = self.query_one("#monitor", DataTable)
        by_id = {d.id: d for d in self._devices}
        keys = ["state", "zone", "grp", "code", "name", "ip", "resp", "loss", "last", "avg", "down"]
        for device_id in self._monitor_rows:
            d = by_id.get(device_id)
            if d is None:
                continue
            for key, value in zip(keys, self._monitor_cells(d)):
                if key in ("state", "resp", "loss", "last", "avg", "down"):
                    table.update_cell(str(device_id), key, value)
        self._update_summary()

    def _update_summary(self) -> None:
        watched = [d for d in self._devices if d.monitored and d.ip
                   and (self.zone_filter == ALL_ZONES or d.zone_id == self.zone_filter)]
        states = [self.monitor.status(d.id).state for d in watched]
        up, down, pending = states.count(UP), states.count(DOWN), states.count(PENDING)
        flags = []
        if self.down_only:
            flags.append("solo caídos")
        if self.show_unmonitored:
            flags.append("incluye no operativos")
        extra = f"   [dim]({', '.join(flags)})[/]" if flags else ""
        self.query_one("#summary", Static).update(
            f"[bold green]Arriba {up}[/]   [bold red]Caídos {down}[/]   Esperando {pending}   "
            f"Monitoreados {len(watched)}{extra}"
        )

    def _on_state_change(self, device_id: int, state: str, ts: datetime) -> None:
        self.inv.record_event(device_id, state, ts)
        if state == DOWN:
            d = next((x for x in self._devices if x.id == device_id), None)
            if d:
                self.notify(f"{d.zone_name} / {d.label} ({d.ip}) no responde", title="Equipo caído",
                            severity="error", timeout=6)

    def action_toggle_down_only(self) -> None:
        self.down_only = not self.down_only
        self._rebuild_monitor()

    def action_toggle_all(self) -> None:
        self.show_unmonitored = not self.show_unmonitored
        self._rebuild_monitor()

    def action_history(self) -> None:
        device = self._focused_device()
        if device:
            self.push_screen(HistoryScreen(device, self.inv.events(device.id)))

    # --- admin tab ---

    def _load_admin(self) -> None:
        zones_table = self.query_one("#zones", DataTable)
        row = zones_table.cursor_row
        zones_table.clear()
        for z in self.inv.zones():
            zones_table.add_row(z.name, str(z.device_count), key=str(z.id))
        if zones_table.row_count:
            zones_table.move_cursor(row=min(row, zones_table.row_count - 1))
        self._load_admin_devices()

    def _selected_zone_id(self) -> int | None:
        table = self.query_one("#zones", DataTable)
        if not table.row_count:
            return None
        key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return int(key.value)

    def _load_admin_devices(self) -> None:
        table = self.query_one("#devices", DataTable)
        row = table.cursor_row
        table.clear()
        zone_id = self._selected_zone_id()
        zone = next((z for z in self.inv.zones() if z.id == zone_id), None)
        self.query_one("#devices-title", Label).update(f"Equipos de {zone.name}" if zone else "Equipos")
        if zone_id is None:
            return
        for d in self.inv.devices(zone_id):
            table.add_row(d.grp, d.code, d.name, d.ip or "-", "Sí" if d.monitored else "No", d.notes,
                          key=str(d.id))
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))

    @on(DataTable.RowHighlighted, "#zones")
    def _zone_highlighted(self) -> None:
        self._load_admin_devices()

    def _focused_device(self) -> Device | None:
        tabs = self.query_one("#tabs", TabbedContent)
        table_id = "#monitor" if tabs.active == "tab-monitor" else "#devices"
        table = self.query_one(table_id, DataTable)
        if not table.row_count:
            return None
        key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return self.inv.device(int(key.value))

    def _admin_target(self) -> str | None:
        """Which admin list the action applies to: 'zone' or 'device'."""
        if self.query_one("#tabs", TabbedContent).active == "tab-monitor":
            return "device"
        return "zone" if self.query_one("#zones", DataTable).has_focus else "device"

    def _zone_options(self) -> list[tuple[str, int]]:
        return [(z.name, z.id) for z in self.inv.zones()]

    def _validate_device(self, values: dict, device_id: int | None = None) -> str | None:
        from .db import normalize_ip
        try:
            normalize_ip(values["ip"])
        except ValueError as exc:
            return str(exc)
        if not values["code"].strip() and not values["name"].strip():
            return "El equipo necesita un código o un nombre."
        ip = (values["ip"] or "").strip()
        clash = [d for d in self.inv.devices() if ip and d.ip == ip and d.id != device_id]
        if clash:
            self.notify(f"La IP {ip} ya la usa {clash[0].zone_name} / {clash[0].label}.",
                        title="IP repetida", severity="warning")
        return None

    def action_add(self) -> None:
        if self._admin_target() == "zone":
            self.push_screen(ZoneForm("Nueva zona"), self._zone_added)
            return
        if self.inv.is_empty():
            self.notify("Primero crea una zona.", severity="warning")
            return
        zone_id = self._selected_zone_id() or self.inv.zones()[0].id
        self.push_screen(DeviceForm("Nuevo equipo", self._zone_options(), zone_id,
                                    validate=self._validate_device), self._device_added)

    def action_edit(self) -> None:
        if self._admin_target() == "zone":
            zone_id = self._selected_zone_id()
            zone = next((z for z in self.inv.zones() if z.id == zone_id), None)
            if zone:
                self.push_screen(ZoneForm("Renombrar zona", zone.name),
                                 lambda name: self._zone_renamed(zone.id, name))
            return
        device = self._focused_device()
        if device:
            self.push_screen(
                DeviceForm(f"Editar {device.label}", self._zone_options(), device.zone_id, device,
                           validate=lambda v: self._validate_device(v, device.id)),
                lambda values: self._device_edited(device.id, values),
            )

    def action_delete(self) -> None:
        if self._admin_target() == "zone":
            zone_id = self._selected_zone_id()
            zone = next((z for z in self.inv.zones() if z.id == zone_id), None)
            if zone:
                self.push_screen(
                    ConfirmScreen(f"¿Eliminar la zona {zone.name!r} y sus {zone.device_count} equipos? "
                                  "También se borra su historial."),
                    lambda ok: self._run_and_reload(ok, self.inv.delete_zone, zone.id,
                                                    f"Zona {zone.name} eliminada"),
                )
            return
        device = self._focused_device()
        if device:
            self.push_screen(
                ConfirmScreen(f"¿Eliminar el equipo {device.zone_name} / {device.label} "
                              f"({device.ip or 'sin IP'})?"),
                lambda ok: self._run_and_reload(ok, self.inv.delete_device, device.id,
                                                f"Equipo {device.label} eliminado"),
            )

    def action_import(self) -> None:
        self.push_screen(ImportForm(), self._import_chosen)

    def _import_chosen(self, choice: tuple[str, bool] | None) -> None:
        from .importer import import_workbook

        if choice is None:
            return
        path, replace = choice
        try:
            report = import_workbook(self.inv, path, replace=replace)
        except ValueError as exc:
            self.notify(f"{exc} En esta pantalla: activa 'Reemplazar todo'.", severity="error", timeout=10)
            return
        except Exception as exc:  # unreadable or non-xlsx file
            self.notify(f"No se pudo leer el archivo: {exc}", severity="error", timeout=10)
            return
        self.notify(f"Importados {report.total} equipos en {len(report.zones)} zonas.", title="Importación")
        for warning in report.warnings:
            self.notify(warning, title="Aviso de importación", severity="warning", timeout=15)
        self.run_worker(self.reload(), exclusive=True, group="reload")

    def _run_and_reload(self, ok, func, arg, message: str) -> None:
        if not ok:
            return
        func(arg)
        self.notify(message)
        self.run_worker(self.reload(), exclusive=True, group="reload")

    def _zone_added(self, name: str | None) -> None:
        self._zone_saved(lambda: self.inv.add_zone(name), name, f"Zona {name} creada")

    def _zone_renamed(self, zone_id: int, name: str | None) -> None:
        self._zone_saved(lambda: self.inv.rename_zone(zone_id, name), name, f"Zona renombrada a {name}")

    def _zone_saved(self, action, name, message) -> None:
        if name is None:
            return
        try:
            action()
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(message)
        self.run_worker(self.reload(), exclusive=True, group="reload")

    def _device_added(self, values: dict | None) -> None:
        self._device_saved(lambda: self.inv.add_device(**values), values, "Equipo agregado")

    def _device_edited(self, device_id: int, values: dict | None) -> None:
        self._device_saved(lambda: self.inv.update_device(device_id, **values), values, "Equipo actualizado")

    def _device_saved(self, action, values, message) -> None:
        if values is None:
            return
        try:
            action()
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(message)
        self.run_worker(self.reload(), exclusive=True, group="reload")

    async def on_unmount(self) -> None:
        await self.monitor.stop_all()
