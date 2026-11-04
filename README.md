# Monitor de red

Programa para Windows que muestra en la terminal, en tiempo real, qué equipos de la red están respondiendo y cuáles están caídos.

Este repositorio solo publica las versiones del programa y no contiene código fuente.

## Qué hace

- **Monitor:** hace ping continuo a cada equipo. Muestra su estado, su tiempo de respuesta y cuándo respondió por última vez, con filtros por zona, grupo, subred y estado.
- **Historial:** guarda cada caída y regreso con su hora, y también los periodos en que el monitor no estuvo activo.
- **Administración:** permite crear zonas y equipos, o importarlos desde un Excel de inventario.
- **Configuración:** permite seguir monitoreando con la ventana cerrada e iniciar el programa con Windows.

## Descargar e instalar

1. Descarga **[MonitorRed-windows.zip](https://github.com/Ds0957/monitor-red/releases/latest/download/MonitorRed-windows.zip)**.
2. Descomprímelo.
3. Haz doble clic en `instalar.bat`.

No necesita Python ni permisos de administrador.

> El `.exe` no está firmado. Si Windows SmartScreen muestra "Windows protegió su PC", pulsa *Más información* y luego *Ejecutar de todas formas*.

## Actualizar

El programa avisa cuando hay una versión nueva. Pulsa `U` y confirma: la descarga, comprueba su suma SHA-256 y se instala sola. Zonas, equipos e historial se conservan.

Las novedades de cada versión están en [Releases](https://github.com/Ds0957/monitor-red/releases).
