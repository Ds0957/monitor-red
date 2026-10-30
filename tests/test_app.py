from textual.widgets import DataTable, Input, Switch

from monired.app import ConfirmScreen, DeviceForm, MonitorApp, ZoneForm
from monired.pinger import DOWN, Monitor


def make_app(inv, fake_ping):
    return MonitorApp(inv, Monitor(interval=0.05, down_after=2, ping_cmd=fake_ping))


def column(table: DataTable, key: str) -> list[str]:
    return [str(table.get_cell(row.key, key)) for row in table.ordered_rows]


async def wait_for(pilot, condition, tries=60):
    for _ in range(tries):
        if condition():
            return True
        await pilot.pause(0.05)
    return condition()


async def test_monitor_shows_live_state_and_records_downtime(inv, fake_ping):
    zid = inv.add_zone("Salones")
    up = inv.add_device(zid, code="R1-2", ip="10.0.0.1")
    down = inv.add_device(zid, code="R3-2", ip="10.0.0.2")
    inv.add_device(zid, code="R1-1", ip="10.0.0.3", monitored=False)

    app = make_app(inv, fake_ping)
    async with app.run_test() as pilot:
        table = app.query_one("#monitor", DataTable)
        assert column(table, "code") == ["R1-2", "R3-2"]          # not-operational hidden

        assert await wait_for(pilot, lambda: column(table, "state") == ["OK", "CAÍDO"])
        assert [e.state for e in inv.events(down)] == [DOWN]
        assert inv.events(up) == []

        await pilot.press("f")                                     # only down devices
        assert column(table, "code") == ["R3-2"]
        await pilot.press("f", "n")                                # all, including not-operational
        assert column(table, "code") == ["R1-2", "R3-2", "R1-1"]
        assert column(table, "state")[2] == "NO OPER."


async def test_import_from_the_ui(inv, fake_ping, tmp_path):
    from openpyxl import Workbook

    from monired.app import ImportForm

    wb = Workbook()
    wb.active.title = "Salones"
    wb.active.append(["Ciclo", "Código del salón", "IP", "Estado"])
    wb.active.append(["Roja", "R1-2", "10.0.0.1", "Operativo"])
    path = tmp_path / "red.xlsx"
    wb.save(path)

    inv.add_zone("Vieja")
    app = make_app(inv, fake_ping)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.press("i")
        form = app.screen
        assert isinstance(form, ImportForm)
        form.query_one("#path", Input).value = str(tmp_path / "nope.xlsx")
        form.query_one("#save").press()
        await pilot.pause()
        assert "No existe el archivo" in str(form.query_one("#error").render())

        # Quoted like Explorer's "Copy as path"; without "replace" a non-empty base is kept.
        form.query_one("#path", Input).value = f'"{path}"'
        form.query_one("#save").press()
        await pilot.pause(0.2)
        assert [z.name for z in inv.zones()] == ["Vieja"]

        await pilot.press("i")
        app.screen.query_one("#path", Input).value = str(path)
        app.screen.query_one("#replace", Switch).value = True
        app.screen.query_one("#save").press()
        await pilot.pause(0.3)
        assert [z.name for z in inv.zones()] == ["Salones"]
        assert column(app.query_one("#monitor", DataTable), "code") == ["R1-2"]


async def test_admin_add_edit_delete_zone_and_device(inv, fake_ping):
    inv.add_zone("Salones")
    app = make_app(inv, fake_ping)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#tabs").active = "tab-admin"
        await pilot.pause()

        # New zone from the zones list.
        app.query_one("#zones", DataTable).focus()
        await pilot.press("a")
        assert isinstance(app.screen, ZoneForm)
        # Typed for real: letters that are also app shortcuts (f, n, a) must reach the input.
        await pilot.press(*"Oficinas", "enter")
        await pilot.pause(0.2)
        assert [z.name for z in inv.zones()] == ["Salones", "Oficinas"]

        # New device in the selected zone, with an invalid IP first.
        app.query_one("#devices", DataTable).focus()
        await pilot.press("a")
        form = app.screen
        assert isinstance(form, DeviceForm)
        form.query_one("#code", Input).value = "R1-2"
        form.query_one("#ip", Input).value = "10.0.0.999"
        form.query_one("#save").press()
        await pilot.pause()
        assert "IP inválida" in str(form.query_one("#error").render())
        form.query_one("#ip", Input).value = "10.0.0.1"
        form.query_one("#save").press()
        await pilot.pause(0.2)
        (device,) = inv.devices()
        assert (device.zone_name, device.code, device.ip) == ("Salones", "R1-2", "10.0.0.1")
        assert app.monitor.targets() == {device.id: "10.0.0.1"}

        # Edit: mark as not operational -> it stops being pinged.
        await pilot.press("e")
        app.screen.query_one("#monitored", Switch).value = False
        app.screen.query_one("#save").press()
        await pilot.pause(0.2)
        assert inv.device(device.id).monitored is False
        assert app.monitor.targets() == {}

        # Delete the device (cancel first, then confirm).
        await pilot.press("d")
        assert isinstance(app.screen, ConfirmScreen)
        app.screen.query_one("#no").press()
        await pilot.pause()
        assert inv.device(device.id) is not None
        await pilot.press("d")
        app.screen.query_one("#yes").press()
        await pilot.pause(0.2)
        assert inv.devices() == []

        # Delete a whole zone.
        app.query_one("#zones", DataTable).focus()
        await pilot.press("d")
        app.screen.query_one("#yes").press()
        await pilot.pause(0.2)
        assert [z.name for z in inv.zones()] == ["Oficinas"]
