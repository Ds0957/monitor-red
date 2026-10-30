# Monitor de red

Inventario de IPs por zona y ping en tiempo real, todo en la terminal.

- **Monitor:** ping continuo a cada equipo operativo; la tabla se actualiza al instante y cada caída/regreso queda guardada con su hora.
- **Administración:** crear, renombrar y eliminar zonas; agregar, editar y eliminar equipos (IP, código, grupo, notas, operativo sí/no).
- **Importación:** carga el Excel de inventario; cada hoja se convierte en una zona.

## Instalación

```bash
cd ~/projects/monitor-red
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
ln -sf "$PWD/.venv/bin/monired" ~/.local/bin/monired
```

## Uso

```bash
monired importar "Organización de Red de Equipos Sede Principal.xlsx"   # primera carga
monired importar archivo.xlsx --reemplazar                            # borra la base y vuelve a cargar
monired                                                               # abre el monitor
monired monitor --intervalo 0.5 --caido-tras 3                        # ping cada 0.5 s, caído tras 3 fallos
```

La base vive en `~/.local/share/monitor-red/red.db` (se cambia con `--db` o la variable `MONIRED_DB`).

### Teclas

| Tecla | Dónde | Acción |
|---|---|---|
| `f` | Monitor | Mostrar solo los equipos caídos |
| `n` | Monitor | Mostrar también los no operativos y los que no tienen IP |
| `h` | Monitor / Administración | Historial de caídas del equipo seleccionado |
| `a` | Administración | Agregar zona (si la lista de zonas tiene el foco) o equipo |
| `e` | Administración / Monitor | Editar zona o equipo |
| `d` / `Supr` | Administración / Monitor | Eliminar zona (con todos sus equipos) o equipo, con confirmación |
| `Tab` | | Cambiar el foco entre listas |
| `q` | | Salir |

El selector de arriba en el monitor filtra por zona.

## Estados

| Estado | Significado |
|---|---|
| `OK` verde | Responde sin pérdidas |
| `OK` amarillo | Responde, pero ha perdido algún ping |
| `CAÍDO` | Lleva `--caido-tras` pings seguidos sin respuesta (2 por defecto) |
| `...` | Esperando la primera respuesta |
| `NO OPER.` / `SIN IP` | No se monitorea |

## Importación

Cada hoja es una zona. Se reconocen las columnas por su encabezado: `IP`, `Código` / `Código del salón`, `Sede` y `Ciclo` (forman el grupo), `Cargo`, `Estado` (`No Operativo` = no se monitorea) y `Observaciones`. Las hojas sin encabezado (como Estáticas) se leen como "nombre + IP". Se avisa de IPs inválidas y repetidas.

## Pruebas

```bash
.venv/bin/pytest
```

## Windows (nativo)

En Windows el ping usa la API ICMP del sistema (`IcmpSendEcho`), sin depender del idioma de `ping` ni de permisos de administrador. La base se guarda en `%LOCALAPPDATA%\MonitorRed\red.db`.

Generar el ejecutable y el paquete (en Windows, con Python 3.10+):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
```

Resultado en `dist\`:
- `MonitorRed-windows\MonitorRed.exe`: ejecutable portable (no necesita Python).
- `MonitorRed-windows.zip`: el exe más `instalar.bat` / `instalar.ps1` (instala para el usuario actual con accesos directos en Escritorio y menú Inicio), `desinstalar.*` y `LEEME.txt`.

Instalar en otro PC: descomprimir el zip y hacer doble clic en `instalar.bat`, o desde PowerShell:

```powershell
.\instalar.ps1 -Excel "C:\ruta\Organización de Red de Equipos Sede Principal.xlsx"
```

Dentro del programa, la tecla `i` importa un Excel sin usar la línea de comandos.
