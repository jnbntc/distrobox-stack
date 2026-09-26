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

`.github/workflows/ghcr-publish.yml` construye y publica semanalmente y ante cambios en Containerfiles/scripts. Además ejecuta smoke tests básicos para books-ops, re-ops y sec-ops.

## Almacenamiento

Podman rootless y rootful se mantienen fuera del filesystem principal bajo `/var/mnt/storage`. Mantener los contextos SELinux adecuados en esos graphroots.
