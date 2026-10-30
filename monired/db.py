"""SQLite inventory: zones, devices and the up/down event history."""

from __future__ import annotations

import ipaddress
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS zones (
    id       INTEGER PRIMARY KEY,
    name     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS devices (
    id        INTEGER PRIMARY KEY,
    zone_id   INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    grp       TEXT    NOT NULL DEFAULT '',
    code      TEXT    NOT NULL DEFAULT '',
    name      TEXT    NOT NULL DEFAULT '',
    ip        TEXT,
    monitored INTEGER NOT NULL DEFAULT 1,
    notes     TEXT    NOT NULL DEFAULT '',
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts        TEXT    NOT NULL,
    state     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS events_device ON events(device_id, ts);
"""


@dataclass(frozen=True)
class Zone:
    id: int
    name: str
    position: int
    device_count: int = 0


@dataclass(frozen=True)
class Device:
    id: int
    zone_id: int
    zone_name: str
    grp: str
    code: str
    name: str
    ip: str | None
    monitored: bool
    notes: str

    @property
    def label(self) -> str:
        return self.code or self.name or (self.ip or f"#{self.id}")


@dataclass(frozen=True)
class Event:
    ts: datetime
    state: str


def normalize_ip(value: str | None) -> str | None:
    """Return a canonical IPv4 string, None for an empty value, or raise ValueError."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        raise ValueError(f"IP inválida: {text!r}") from None


class Inventory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- zones ---

    def zones(self) -> list[Zone]:
        rows = self.conn.execute(
            """SELECT z.id, z.name, z.position, COUNT(d.id) AS n
               FROM zones z LEFT JOIN devices d ON d.zone_id = z.id
               GROUP BY z.id ORDER BY z.position, z.id"""
        )
        return [Zone(r["id"], r["name"], r["position"], r["n"]) for r in rows]

    def zone_by_name(self, name: str) -> Zone | None:
        return next((z for z in self.zones() if z.name.lower() == name.strip().lower()), None)

    def add_zone(self, name: str) -> int:
        name = self._zone_name(name)
        pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM zones").fetchone()[0]
        with self.conn:
            cur = self.conn.execute("INSERT INTO zones(name, position) VALUES (?, ?)", (name, pos))
        return cur.lastrowid

    def rename_zone(self, zone_id: int, name: str) -> None:
        name = self._zone_name(name, exclude_id=zone_id)
        with self.conn:
            self.conn.execute("UPDATE zones SET name = ? WHERE id = ?", (name, zone_id))

    def delete_zone(self, zone_id: int) -> None:
        """Delete a zone together with all its devices and their history."""
        with self.conn:
            self.conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))

    def _zone_name(self, name: str, exclude_id: int | None = None) -> str:
        name = name.strip()
        if not name:
            raise ValueError("El nombre de la zona no puede estar vacío.")
        clash = self.zone_by_name(name)
        if clash and clash.id != exclude_id:
            raise ValueError(f"Ya existe una zona llamada {clash.name!r}.")
        return name

    # --- devices ---

    def devices(self, zone_id: int | None = None) -> list[Device]:
        sql = """SELECT d.*, z.name AS zone_name FROM devices d JOIN zones z ON z.id = d.zone_id"""
        args: tuple = ()
        if zone_id is not None:
            sql += " WHERE d.zone_id = ?"
            args = (zone_id,)
        sql += " ORDER BY z.position, z.id, d.position, d.id"
        return [self._device(r) for r in self.conn.execute(sql, args)]

    def device(self, device_id: int) -> Device | None:
        row = self.conn.execute(
            "SELECT d.*, z.name AS zone_name FROM devices d JOIN zones z ON z.id = d.zone_id WHERE d.id = ?",
            (device_id,),
        ).fetchone()
        return self._device(row) if row else None

    def add_device(
        self,
        zone_id: int,
        *,
        grp: str = "",
        code: str = "",
        name: str = "",
        ip: str | None = None,
        monitored: bool = True,
        notes: str = "",
    ) -> int:
        fields = self._device_fields(zone_id, grp, code, name, ip, monitored, notes)
        pos = self.conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM devices WHERE zone_id = ?", (zone_id,)
        ).fetchone()[0]
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO devices(zone_id, grp, code, name, ip, monitored, notes, position)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (*fields, pos),
            )
        return cur.lastrowid

    def update_device(
        self,
        device_id: int,
        *,
        zone_id: int,
        grp: str,
        code: str,
        name: str,
        ip: str | None,
        monitored: bool,
        notes: str,
    ) -> None:
        fields = self._device_fields(zone_id, grp, code, name, ip, monitored, notes)
        with self.conn:
            self.conn.execute(
                """UPDATE devices SET zone_id = ?, grp = ?, code = ?, name = ?, ip = ?,
                   monitored = ?, notes = ? WHERE id = ?""",
                (*fields, device_id),
            )

    def delete_device(self, device_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    def _device_fields(self, zone_id, grp, code, name, ip, monitored, notes) -> tuple:
        if not self.conn.execute("SELECT 1 FROM zones WHERE id = ?", (zone_id,)).fetchone():
            raise ValueError("La zona indicada no existe.")
        code, name = code.strip(), name.strip()
        if not code and not name:
            raise ValueError("El equipo necesita un código o un nombre.")
        return (zone_id, grp.strip(), code, name, normalize_ip(ip), int(bool(monitored)), notes.strip())

    def duplicate_ips(self) -> dict[str, list[Device]]:
        by_ip: dict[str, list[Device]] = {}
        for d in self.devices():
            if d.ip:
                by_ip.setdefault(d.ip, []).append(d)
        return {ip: ds for ip, ds in by_ip.items() if len(ds) > 1}

    @staticmethod
    def _device(r: sqlite3.Row) -> Device:
        return Device(
            r["id"], r["zone_id"], r["zone_name"], r["grp"], r["code"], r["name"],
            r["ip"], bool(r["monitored"]), r["notes"],
        )

    # --- events ---

    def record_event(self, device_id: int, state: str, ts: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO events(device_id, ts, state) VALUES (?, ?, ?)",
                (device_id, ts.isoformat(timespec="seconds"), state),
            )

    def events(self, device_id: int, limit: int = 50) -> list[Event]:
        rows = self.conn.execute(
            "SELECT ts, state FROM events WHERE device_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
            (device_id, limit),
        )
        return [Event(datetime.fromisoformat(r["ts"]), r["state"]) for r in rows]

    # --- bulk ---

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM zones").fetchone()[0] == 0

    def clear(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM zones")
