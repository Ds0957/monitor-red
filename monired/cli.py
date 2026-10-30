"""Command line entry point: `monired` opens the terminal UI, `monired importar` loads a spreadsheet."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .db import Inventory


def _default_db() -> Path:
    if os.environ.get("MONIRED_DB"):
        return Path(os.environ["MONIRED_DB"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MonitorRed" / "red.db"
    return Path.home() / ".local/share/monitor-red/red.db"


DEFAULT_DB = _default_db()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="monired", description="Monitor de red en terminal.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"base de datos (por defecto {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("monitor", help="abre el monitor (comando por defecto)")
    run.add_argument("--intervalo", type=float, default=1.0, help="segundos entre pings (mínimo 0.2)")
    run.add_argument("--caido-tras", type=int, default=2, help="pings perdidos seguidos para marcar caído")

    imp = sub.add_parser("importar", help="importa el Excel de inventario (una hoja = una zona)")
    imp.add_argument("archivo", type=Path)
    imp.add_argument("--reemplazar", action="store_true", help="borra la base actual antes de importar")

    args = parser.parse_args(argv)
    inv = Inventory(args.db)
    try:
        if args.command == "importar":
            return _import(inv, args.archivo, args.reemplazar)
        interval = getattr(args, "intervalo", 1.0)
        down_after = getattr(args, "caido_tras", 2)
        if interval < 0.2:
            parser.error("--intervalo debe ser 0.2 o mayor")
        if down_after < 1:
            parser.error("--caido-tras debe ser 1 o mayor")
        return _monitor(inv, interval, down_after)
    finally:
        inv.close()


def _import(inv: Inventory, path: Path, replace: bool) -> int:
    from .importer import import_workbook

    if not path.exists():
        print(f"No existe el archivo: {path}", file=sys.stderr)
        return 1
    try:
        report = import_workbook(inv, path, replace=replace)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception as exc:  # unreadable or non-xlsx file
        print(f"No se pudo leer el archivo: {exc}", file=sys.stderr)
        return 1
    print(f"Importados {report.total} equipos en {len(report.zones)} zonas:")
    for zone, count in report.zones.items():
        print(f"  {zone:<25} {count:>4}")
    if report.warnings:
        print(f"\nAvisos ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  - {w}")
    return 0


def _monitor(inv: Inventory, interval: float, down_after: int) -> int:
    from .app import MonitorApp
    from .pinger import Monitor, default_probe

    MonitorApp(inv, Monitor(interval=interval, down_after=down_after, probe=default_probe())).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
