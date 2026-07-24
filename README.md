# Distrobox Stack — Declarative OCI Workspaces for Fedora Atomic

Stack de infraestructura como código (IaC) para la orquestación declarativa de entornos de trabajo especializados y descartables sobre **Fedora Atomic** (Silverblue / Kinoite / Sway Atomic). 

El proyecto apalanca **Podman** (Driver OverlayFS) y **Distrobox** para aislar herramientas de red, desarrollo IoT, inteligencia artificial, scripting y multimedia del host inmutable, redirigiendo el 100% de la capa de almacenamiento (GraphRoot) hacia un disco NVMe secundario dedicado con endurecimiento estricto de **SELinux**.

---

## 🏗️ Arquitectura de Almacenamiento & SELinux

Para evitar el desgaste y la saturación del sistema de archivos principal (`/var`), el motor de Podman está segmentado físicamente en el disco secundario (`/var/mnt/storage`) separando los namespaces de ejecución privilegiada y de espacio de usuario:

```text
/var/mnt/storage/
├── podman-rootful/          <-- GraphRoot (sudo podman) | SELinux: container_var_lib_t
│   └── storage/overlay/     # Capas e imágenes de net-ops (Rootful)
└── podman-rootless/         <-- GraphRoot (user podman) | SELinux: container_var_lib_t
    └── $USER/storage/       # Capas e imágenes rootless (ia-dev, iot-dev, media-ops, pwsh)
```

### Configuración del Driver (`storage.conf`)
Ambos demonios (Rootful en `/etc/containers/storage.conf` y Rootless en `~/.config/containers/storage.conf`) operan bajo el siguiente estándar de optimización I/O:

```ini
[storage]
driver = "overlay"
# RunRoot apunta a tmpfs (/var/run o /run/user/$UID) para evitar cuellos de botella en disco
graphroot = "/var/mnt/storage/podman-[rootful|rootless]/[$USER/]storage"

[storage.options.overlay]
mountopt = "nodev,metacopy=on" # metacopy=on acelera I/O evitando duplicar metadata entre capas
```

> **Nota de Seguridad (SELinux):** Todo el árbol de `/var/mnt/storage/podman-*` debe mantener el contexto `container_var_lib_t` (`chcon -R -t container_var_lib_t /ruta`) para permitir la escritura nativa del motor OCI y el reetiquetado dinámico de volúmenes (`:z` / `:Z`) sin bloqueos del kernel en hosts Atomic.

---

## 📦 Catálogo de Entornos (Manifiestos OCI)

Las imágenes se compilan localmente desde la carpeta `dockerfiles/` optimizando las dependencias nativas (`dnf`/`apt`) mediante políticas *Zero-Bloat* (sin documentación, sin recomendaciones débiles como TeX Live/LaTeX).

| Contenedor | Contexto | Red / HW | Descripción & Stack Principal |
| :--- | :--- | :--- | :--- |
| **`net-ops`** | **Rootful** (`root=true`) | `host` / Sockets Raw | Auditoría L2/L3, troubleshooting y telemetría. Capas de kernel habilitadas: `NET_ADMIN`, `NET_RAW`, `NET_BIND_SERVICE`. <br>• **Stack:** `nmap`, `wireshark-cli`, `tcpdump`, `lldpd`, `ethtool`, `scapy`, `iperf3`, `bmon`, `net-snmp-utils`, `mosquitto`. |
| **`pwsh-admin`** | **Rootless** | Bridge genérico | Automatización, scripting de administración y gestión de infraestructura SysAdmin sobre PowerShell / Python3. |
| **`iot-dev`** | **Rootless** | USB Bus Mapped | Programación y flasheo de microcontroladores (ESP32-S3, Arduino, ARM). <br>• **HW Mapping:** Montaje dinámico del bus (`--device /dev/bus/usb:/dev/bus/usb:rwm`) + `--group-add keep-groups` para **Hot-Plugging** serial real (evita caídas de recreación si la placa no está conectada). |
| **`ia-dev`** | **Rootless** | GPU / DRI Mapped | Desarrollo e inferencia local de IA, LLMs y Agentes. Soporte preparado para mapeo de aceleración por hardware (`/dev/dri`). |
| **`media-ops`** | **Rootless** | Bridge genérico | Operaciones, transcodificación y procesamiento de streams multimedia en espacio de usuario. |

---

## 📂 Estructura del Repositorio

```text
.
├── .github/workflows/
│   └── linter.yml          # Pipeline CI/CD: Hadolint (OCI) + ShellCheck (Bash)
├── dockerfiles/            # Manifiestos inmutables de construcción (Containerfiles)
│   ├── Containerfile.ia-dev
│   ├── Containerfile.iot-dev
│   ├── Containerfile.media-ops
│   ├── Containerfile.net-ops
│   └── Containerfile.pwsh-admin
├── scripts/
│   └── stack.sh            # Motor de automatización y ciclo de vida de contenedores
├── distrobox.ini           # Especificación declarativa de ensamblado (Distrobox Assemble)
├── Makefile                # Wrappers de ejecución para orquestación rápida
├── .containerignore        # Exclusiones de build context (Zero-layer busting)
└── .gitignore
```

---

## 🚀 Gestión Operativa (`stack.sh`)

La administración del ciclo de vida se centraliza en `scripts/stack.sh` (o mediante sus targets en el `Makefile`). El script gestiona de forma transparente la separación de privilegios al compilar (`sudo podman` vs `podman`) para poblar los almacenes de almacenamiento respectivos.

```bash
# 1. Compilar el stack de imágenes OCI localmente (Rootful + Rootless)
./scripts/stack.sh build

# 2. Desplegar o actualizar las cajas declaradas en distrobox.ini (sin alterar existentes)
./scripts/stack.sh deploy

# 3. Reconstrucción total (Compila e invoca assemble --replace en un solo paso)
./scripts/stack.sh recreate

# 4. Purga de limpieza (Elimina imágenes locales huérfanas o dangling)
./scripts/stack.sh clean
```

### Orquestación Declarativa (`distrobox assemble`)
El despliegue no utiliza bucles destructivos ni interactúa con sockets individuales; delega la convergencia de estado a Distrobox:

```bash
distrobox assemble create --replace --file distrobox.ini
```

*El flag `--replace` evalúa el parámetro `root=true|false` de cada bloque INI, reemplazando el contenedor en el namespace exacto del host sin conflictos de permisos.*

---

## 🛡️ CI/CD & Hardening

El repositorio incluye validación continua en `.github/workflows/linter.yml` bajo dos niveles de auditoría:
1. **ShellCheck (`severity: error`):** Bloquea integraciones si los scripts de automatización presentan fallos lógicos, expansiones variables sin comillas dobles o redirecciones malformadas.
2. **Hadolint (OCI Linter):** Audita los `Containerfiles` validando buenas prácticas en contenedores de sistema, con reglas de exclusión adaptadas a entornos *rolling-release* locales (`ignore: DL3007,DL3008,DL3041` para permitir `:latest` y autogestión de paquetería de repositorios nativos).

---

## 💡 Recomendaciones de Evolución Arquitectónica

* **Pruning Automatizado (Systemd Timers):** Al trabajar con reconstrucciones frecuentes (`recreate`), el almacenamiento de OverlayFS puede acumular blobs inactivos en `/var/mnt/storage`. Se sugiere implementar un *timer* de usuario en systemd (`~/.config/systemd/user/podman-prune.timer`) que ejecute `podman system prune -f` semanalmente.
* **Integración con GHCR (Cloud Caching):** Para provisionar nuevos hosts Atomic en segundos sin compilar localmente, se puede agregar un *job* al workflow de GitHub Actions que compile y publique las capas en el GitHub Container Registry (`ghcr.io/<user>/net-ops:latest`), cambiando el parámetro `pull=false` por `true` en el `distrobox.ini`.
