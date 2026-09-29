# Distrobox Stack — Declarative OCI Workspaces for Fedora Atomic

Stack declarativo de entornos especializados sobre Fedora Atomic usando Podman, Distrobox y GHCR. El host queda orientado a Flatpak para aplicaciones de escritorio y los toolchains técnicos viven en contenedores reproducibles.

## Arquitectura

- **Flatpak**: aplicaciones gráficas de escritorio, por ejemplo Darktable.
- **Distrobox rootless**: sys-ops, iot-dev, ia-dev, books-ops, gns3-client y re-ops.
- **Distrobox rootful**: net-ops y sec-ops cuando el workflow necesita acceso privilegiado a red/dispositivos.
- **GHCR**: publica las imágenes construidas por GitHub Actions.
- **NVMe secundario**: Podman usa graphroot bajo `/var/mnt/storage`.

> Distrobox prioriza integración con el host, no aislamiento fuerte. No usar estos workspaces como sandbox para ejecutar malware no confiable.

## Contenedores

| Contenedor | Contexto | Propósito |
| --- | --- | --- |
| `sys-ops` | rootless | PowerShell, Kerberos, DNS y administración general. |
| `iot-dev` | rootless + USB | PlatformIO y desarrollo/flasheo de microcontroladores. |
| `ia-dev` | rootless + DRI | Python/uv, Aider e Intel OpenCL/Level Zero. |
| `books-ops` | rootless + USB | Calibre, gestión/conversión de ebooks, Kindle por USB, Tor/torsocks y utilidades de descarga. |
| `gns3-client` | rootless | Cliente GNS3 y Wireshark integrado al escritorio. |
| `re-ops` | rootless + netns aislado | Ghidra headless y análisis estático/firmware. |
| `net-ops` | rootful | Troubleshooting L2/L3, captura, SNMP, LLDP, Scapy, iperf y herramientas de red. |
| `sec-ops` | rootful + netns aislado | Workspace ofensivo/lab con OpenVPN, RustScan, Feroxbuster, Ligolo, pwncat y PEASS. |

## iot-dev

Workspace rootless canónico para PlatformIO y microcontroladores. PlatformIO Core se instala en un venv inmutable bajo `/opt/pio`, separado del Python del sistema.

El estado mutable de PlatformIO (platforms, packages, toolchains, cache y configuración global) **no usa** el `~/.platformio` por defecto. El wrapper de `pio` fija dinámicamente:

```text
PLATFORMIO_CORE_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/platformio
```

Esto evita mezclar paquetes creados por antiguos Dev Containers con el workspace Distrobox y garantiza que el estado global sea escribible por el UID real del usuario.

Incluye `usbutils` y `udev` para diagnóstico de dispositivos. El manifest conserva el acceso explícito a `/dev/bus/usb` y los grupos suplementarios del usuario del host con `--group-add keep-groups`.

Comandos útiles dentro de `iot-dev`:

```bash
pio --version
pio system info
pio device list
lsusb
```

`pio` y `platformio` **no se exportan al host**: `iot-dev` es la única instalación canónica de PlatformIO Core.

Para flashear por `/dev/ttyUSB*` o `/dev/ttyACM*`, el usuario del host debe tener permisos sobre el dispositivo serie; Distrobox conserva esos grupos suplementarios.

### VS Code sobre iot-dev

VS Code se ejecuta en el host y usa la extensión **Dev Containers** para adjuntarse al Distrobox ya existente; los repos embedded no necesitan su propio `.devcontainer/`.

Flujo diario:

```bash
podman start iot-dev
```

Luego, en VS Code:

1. ejecutar **Dev Containers: Attach to Running Container...**;
2. seleccionar `iot-dev`;
3. abrir el proyecto bajo el mismo `$HOME/Proyectos/...` compartido por Distrobox.

Para que VS Code reutilice el único PlatformIO Core de `iot-dev`, abrir **Dev Containers: Open Named Configuration File**, elegir `iot-dev` y usar una configuración equivalente a:

```json
{
  "extensions": [
    "platformio.platformio-ide",
    "ms-vscode.cpptools"
  ],
  "settings": {
    "platformio-ide.useBuiltinPIOCore": false,
    "platformio-ide.customPATH": "/usr/local/bin:/opt/pio/bin:/usr/bin:/bin"
  }
}
```

`/usr/local/bin/pio` es el wrapper canónico del workspace y mantiene el estado mutable bajo `$XDG_DATA_HOME/platformio` (o `$HOME/.local/share/platformio`).

La extensión Dev Containers del host puede usar Podman como backend mediante:

```json
"dev.containers.dockerPath": "/usr/bin/podman"
```

Los Dev Containers por proyecto se reservan para casos donde el repositorio necesite un toolchain o servicios propios que no deban compartirse con un workspace persistente.

## books-ops

Calibre reemplaza el antiguo `media-ops`. Darktable queda como Flatpak en el host.

Incluye `usbutils` para diagnóstico USB y el Kindle se expone al contenedor mediante `/dev/bus/usb`.

Tor no arranca automáticamente. El helper ignora el `/etc/tor/torrc` del paquete y usa un runtime de usuario propio, evitando sockets de control bajo `/run/tor`:

```bash
books-tor start
books-tor status
books-tor check
books-tor logs
torsocks curl https://example.org/
books-tor stop
```

Los binarios `calibredb`, `ebook-convert` y `books-tor` se exportan al path por defecto de Distrobox (`$HOME/.local/bin`), y Calibre se exporta como aplicación gráfica.

## Uso

El host no necesita `make`. El flujo recomendado usa directamente el orquestador:

```bash
./scripts/stack.sh pull
./scripts/stack.sh deploy
```

Recrear todo desde las imágenes actuales de GHCR:

```bash
./scripts/stack.sh recreate
```

Recrear un único workspace:

```bash
./scripts/stack.sh recreate books-ops
```

El `Makefile` se conserva sólo como conveniencia si `make` ya está instalado.

Build local para desarrollo:

```bash
./scripts/stack.sh build books-ops
```

> Las imágenes locales usan `localhost/custom/*`; el deploy normal consume `ghcr.io/jnbntc/*`.

## CI/CD

`.github/workflows/ghcr-publish.yml` construye y publica semanalmente y ante cambios en Containerfiles/scripts. Además ejecuta smoke tests básicos para los workspaces críticos, incluyendo PlatformIO/USB en `iot-dev`.

`.github/workflows/maintenance.yml` aplica una política de retención semanal:

- conserva los **10 runs completados más recientes** por workflow;
- conserva las **3 versiones más recientes** de cada imagen activa en GHCR, protegiendo además cualquier versión etiquetada como `latest`;
- elimina las versiones restantes del paquete obsoleto `media-ops`.

Esto mantiene capacidad de rollback sin acumular indefinidamente tags SHA ni historial de Actions.

## Almacenamiento

Podman rootless y rootful se mantienen fuera del filesystem principal bajo `/var/mnt/storage`. Mantener los contextos SELinux adecuados en esos graphroots.
