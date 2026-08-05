# Distrobox Stack — Declarative OCI Workspaces for Fedora Atomic

Stack de infraestructura como código (IaC) para la orquestación declarativa de entornos de trabajo especializados y descartables sobre **Fedora Atomic** (Silverblue / Kinoite / Sway Atomic). 

El proyecto apalanca **Podman** (Driver OverlayFS), **Distrobox** y **GitHub Container Registry (GHCR)** para aislar herramientas de red, desarrollo IoT, inteligencia artificial, scripting y multimedia del host inmutable, redirigiendo el 100% de la capa de almacenamiento hacia un disco NVMe secundario dedicado con endurecimiento estricto de **SELinux**.

---

## 🏗️ Arquitectura de Almacenamiento & SELinux

Para evitar el desgaste y la saturación del sistema de archivos principal (`/var`), el motor de Podman está segmentado físicamente en el disco secundario (`/var/mnt/storage`) separando los namespaces de ejecución privilegiada y de espacio de usuario:

```text
/var/mnt/storage/
├── podman-rootful/                          <-- GraphRoot (sudo podman) | SELinux: container_var_lib_t
│   └── storage/overlay/                     # Capas e imágenes rootful (net-ops)
└── podman-rootless/                         <-- GraphRoot (user podman) | SELinux: container_var_lib_t
    └── $USER/
        └── storage/                         # Capas rootless (ia-dev, iot-dev, media-ops, pwsh-admin)
            └── volumes/                     # Volúmenes persistentes mapeados al namespace del usuario
```

### Configuración del Driver (`storage.conf`)
Ambos demonios (`/etc/containers/storage.conf` y `~/.config/containers/storage.conf`) operan bajo el siguiente estándar de optimización I/O:

```ini
[storage]
driver = "overlay"
graphroot = "/var/mnt/storage/podman-[rootful|rootless]/[$USER/]storage"

[storage.options.overlay]
mountopt = "nodev,metacopy=on" # metacopy=on acelera I/O evitando duplicar metadata entre capas
```

> **Nota de Seguridad (SELinux):** Todo el árbol de `/var/mnt/storage/podman-*` mantiene el contexto `container_var_lib_t` (`chcon -R -t container_var_lib_t /var/mnt/storage/podman-*`) para permitir la escritura nativa del motor OCI y el reetiquetado dinámico de volúmenes (`:z` / `:Z`) sin bloqueos del kernel.

---

## 📦 Catálogo de Entornos OCI (Zero-Bloat)

Las imágenes se compilan de forma automatizada mediante políticas *Zero-Bloat* (sin documentación, sin recomendaciones débiles de paquetería como TeX Live/LaTeX).

| Contenedor | Contexto | Red / HW | Descripción & Stack Principal |
| :--- | :--- | :--- | :--- |
| **`net-ops`** | **Rootful** (`root=true`) | `host` / Sockets Raw | Auditoría L2/L3, troubleshooting y telemetría. Capas de kernel habilitadas: `NET_ADMIN`, `NET_RAW`, `NET_BIND_SERVICE`. <br>• **Stack:** `nmap`, `wireshark-cli`, `tcpdump`, `lldpd`, `ethtool`, `scapy`, `iperf3`, `bmon`, `net-snmp-utils`, `mosquitto`. |
| **`pwsh-admin`** | **Rootless** | Bridge genérico | Automatización, scripting SysAdmin y gestión de infraestructura sobre PowerShell 7 / Python 3. |
| **`iot-dev`** | **Rootless** | USB Bus Mapped | Programación y flasheo de microcontroladores (ESP32-S3, Arduino, ARM). <br>• **HW Mapping:** Montaje dinámico del bus (`--device /dev/bus/usb:/dev/bus/usb:rwm`) + `--group-add keep-groups` para **Hot-Plugging serial real**. |
| **`ia-dev`** | **Rootless** | GPU / DRI Mapped | Inferencia local, desarrollo de agentes y automatización LLM. Mapeo directo de aceleración por hardware (`/dev/dri`). |
| **`media-ops`** | **Rootless** | Bridge genérico | Operaciones, transcodificación y procesamiento de streams multimedia en espacio de usuario. |
| **`re-ops`** | **Rootless** | Aislado (`unshare_net`) | Ingeniería Inversa (SRE), extracción de IoCs y análisis estático de firmware. <br>• **Stack:** `ghidra` (Headless), `java-21-openjdk-headless`. |

---

## 🚀 CI/CD & Compilación en Nube (GHCR)

La construcción de imágenes se delega a GitHub Actions (`.github/workflows/ghcr-publish.yml`), ejecutándose en cada *push* a la rama principal y programada semanalmente vía cron (`0 3 * * 1`). Las imágenes resultantes se almacenan en el **GitHub Container Registry**:

* `ghcr.io/<owner>/net-ops:latest`
* `ghcr.io/<owner>/pwsh-admin:latest`
* `ghcr.io/<owner>/iot-dev:latest`
* `ghcr.io/<owner>/ia-dev:latest`
* `ghcr.io/<owner>/media-ops:latest`

### Orquestación Declarativa (`distrobox assemble`)
Al estar los artefactos disponibles en GHCR, el despliegue en el host Atomic no requiere compilación local; el manifiesto `distrobox.ini` consume directamente las imágenes cloud:

```bash
distrobox assemble create --replace --file distrobox.ini
```

*El flag `--replace` evalúa el parámetro `root=true|false` de cada bloque INI, reemplazando el contenedor en el namespace exacto del host sin conflictos de permisos.*

---

## 🧹 Pruning Automatizado (Systemd Timers)

El mantenimiento del disco NVMe secundario está orquestado por un servicio desatendido de Systemd en espacio de usuario (`~/.config/systemd/user/podman-prune.service` / `podman-prune.timer`).

* **Programación:** Todos los domingos a las 02:00 AM (`Sun *-*-* 02:00:00`).
* **Operación:** Ejecuta `podman system prune -a -f` y `sudo podman system prune -a -f` para eliminar blobs OCI huérfanos, cachés de compilación y capas OverlayFS inactivas, preservando intactos los volúmenes persistentes de datos.
* **Auditoría:** `journalctl --user -t podman-prune -e`
