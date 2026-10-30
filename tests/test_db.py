from datetime import datetime

import pytest

from monired.db import normalize_ip


def test_zone_crud_and_unique_names(inv):
    zid = inv.add_zone("Salones")
    with pytest.raises(ValueError, match="Ya existe"):
        inv.add_zone("salones")
    with pytest.raises(ValueError, match="vacío"):
        inv.add_zone("   ")
    inv.rename_zone(zid, "Aulas")
    assert [z.name for z in inv.zones()] == ["Aulas"]


def test_deleting_a_zone_removes_its_devices_and_history(inv):
    keep, drop = inv.add_zone("Oficinas"), inv.add_zone("Salones")
    kept = inv.add_device(keep, code="P-RECTORIA", ip="192.168.5.70")
    gone = inv.add_device(drop, code="R1-2", ip="192.168.10.55")
    inv.record_event(gone, "down", datetime(2026, 10, 30, 8, 0))

    inv.delete_zone(drop)

    assert [z.name for z in inv.zones()] == ["Oficinas"]
    assert [d.id for d in inv.devices()] == [kept]
    assert inv.events(gone) == []


def test_device_crud(inv):
    zid = inv.add_zone("Salones")
    other = inv.add_zone("Oficinas")
    did = inv.add_device(zid, grp="Roja", code="R1-2", ip=" 192.168.10.55 ")
    d = inv.device(did)
    assert (d.zone_name, d.code, d.ip, d.monitored) == ("Salones", "R1-2", "192.168.10.55", True)

    inv.update_device(did, zone_id=other, grp="Principal", code="R1-2", name="Aula", ip="",
                      monitored=False, notes="sin red")
    d = inv.device(did)
    assert (d.zone_name, d.ip, d.monitored, d.notes) == ("Oficinas", None, False, "sin red")

    inv.delete_device(did)
    assert inv.device(did) is None


def test_device_validation(inv):
    zid = inv.add_zone("Salones")
    with pytest.raises(ValueError, match="IP inválida"):
        inv.add_device(zid, code="R1-2", ip="192.168.10.300")
    with pytest.raises(ValueError, match="código o un nombre"):
        inv.add_device(zid, ip="192.168.10.55")
    with pytest.raises(ValueError, match="zona indicada no existe"):
        inv.add_device(999, code="X")


def test_duplicate_ips_are_reported(inv):
    zid = inv.add_zone("Salones")
    inv.add_device(zid, code="A", ip="10.0.0.5")
    inv.add_device(zid, code="B", ip="10.0.0.5")
    inv.add_device(zid, code="C", ip="10.0.0.6")
    assert [d.code for d in inv.duplicate_ips()["10.0.0.5"]] == ["A", "B"]
    assert list(inv.duplicate_ips()) == ["10.0.0.5"]


def test_events_newest_first(inv):
    did = inv.add_device(inv.add_zone("Z"), code="A", ip="10.0.0.1")
    inv.record_event(did, "down", datetime(2026, 10, 30, 8, 0, 0))
    inv.record_event(did, "up", datetime(2026, 10, 30, 8, 0, 5))
    assert [e.state for e in inv.events(did)] == ["up", "down"]


def test_normalize_ip():
    assert normalize_ip("") is None
    assert normalize_ip(None) is None
    assert normalize_ip(" 10.0.0.1 ") == "10.0.0.1"
    with pytest.raises(ValueError):
        normalize_ip("-")
