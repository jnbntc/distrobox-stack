# Distrobox Stack — Declarative OCI Workspaces for Fedora Atomic

<p>
  <img src="https://img.shields.io/badge/Fedora-Atomic-51A2DA?style=flat-square&logo=fedora&logoColor=white" alt="Fedora Atomic" />
  <img src="https://img.shields.io/badge/Podman-OCI-892CA0?style=flat-square&logo=podman&logoColor=white" alt="Podman" />
  <img src="https://img.shields.io/badge/Distrobox-Workspaces-333333?style=flat-square" alt="Distrobox" />
  <img src="https://img.shields.io/badge/GHCR-Images-333333?style=flat-square&logo=github&logoColor=white" alt="GHCR" />
</p>

Stack declarativo de entornos especializados sobre Fedora Atomic usando Podman, Distrobox y GHCR. El host queda orientado a Flatpak para aplicaciones de escritorio y los toolchains técnicos viven en contenedores reproducibles.

> **Idea central:** mantener el host pequeño y predecible, y mover los toolchains técnicos a workspaces OCI reproducibles con privilegios explícitos según cada caso.

```text
GitHub Actions → GHCR → Distrobox workspaces
                         ├─ rootless
Fedora Atomic host ──────┤
                         └─ rootful

Desktop apps → Flatpak
```

## Arquitectura

- **Flatpak**: aplicaciones gráficas de escritorio, por ejemplo Darktable.
- **Distrobox rootless**: sys-ops, iot-dev, android-ops, ia-dev, books-ops, gns3-client y re-ops.
- **Distrobox rootful**: net-ops y sec-ops cuando el workflow necesita acceso privilegiado a red/dispositivos.
- **GHCR**: publica las imágenes construidas por GitHub Actions.
- **NVMe secundario**: Podman usa graphroot bajo `/var/mnt/storage`.

> Distrobox prioriza integración con el host, no aislamiento fuerte. No usar estos workspaces como sandbox para ejecutar malware no confiable.

## Contenedores

| Contenedor | Contexto | Propósito |
| --- | --- | --- |
| `sys-ops` | rootless | PowerShell, Kerberos, DNS y administración general. |
| `iot-dev` | rootless + USB | PlatformIO y ESP-IDF nativo para ESP32-S3. |
| `android-ops` | rootless + USB | ADB/Fastboot, inventario y mantenimiento de dispositivos Android. |
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

### ESP-IDF nativo para InfraBadge

`iot-dev` conserva **PlatformIO Core 6.2.0** y agrega **ESP-IDF v5.5.5**, commit
`b774170ff46c393eeb5e495ea37936038d3f4f4f`. Esta versión estable de mantenimiento
de 5.5 incluye correcciones posteriores a 5.5.0 y cumple el mínimo de Waveshare.
La selección se verificó el 15 de octubre de 2026:
[release de Espressif](https://github.com/espressif/esp-idf/releases/tag/v5.5.5) y
[requisito de Waveshare](https://docs.waveshare.com/ESP32-S3-ePaper-1.54/ESP-IDF).

| Parte | Ubicación / estado |
| --- | --- |
| PlatformIO Core y su Python | `/opt/pio`, wrapper existente sin cambios |
| Paquetes y configuración PlatformIO | `${XDG_DATA_HOME:-$HOME/.local/share}/platformio`, persistente |
| SDK ESP-IDF | `/opt/esp/idf`, release y commit verificados durante build |
| Herramientas ESP-IDF | `/opt/esp/tools`, versiones y SHA-256 de `tools/tools.json` del commit |
| Python de ESP-IDF | `/opt/esp/python`, independiente del sistema y de `/opt/pio` |
| Dependencias Python ESP-IDF | `dockerfiles/esp-idf/*.lock`, versiones y hashes; constraints oficiales guardados |
| Estado de proyecto | `sdkconfig`, `dependencies.lock`, `managed_components/`, `build/` dentro del proyecto |
| Caché opcional de compilación | `CCACHE_DIR` escribible del usuario, nunca dentro de `/opt/esp` |

Se instalan sólo las herramientas requeridas para `esp32s3`, incluyendo Xtensa
para las CPU principales y RISC-V/esp32ulp para el coprocesador ULP. No se instala
QEMU, Clang ni toolchains de otros targets por conveniencia. CMake, Ninja, GCC/G++,
Make, Bison, Flex, Gperf, ccache, libffi/libssl de desarrollo, libusb, libpython3.11
y xz provienen de Bookworm. GDB y OpenOCD provienen del manifiesto del SDK.

La imagen base Bookworm Slim está fijada por digest. El SDK usa un clon superficial,
submódulos fijados por el commit y verificación de hashes de las descargas. Los
archivos descargados de herramientas y cachés pip se eliminan en la misma capa.
Se conserva Git para que `idf.py --version` y el build detecten la release; sólo
`/opt/esp/idf` se autoriza como `safe.directory` para usuarios distintos de root.
APT sigue usando los repositorios de Bookworm y PlatformIO conserva su resolución
original de dependencias transitivas: **no se promete una imagen idéntica byte a
byte** entre fechas. Para desplegar exactamente una imagen probada, usar su digest
OCI; actualizar los pins mediante PR, no ejecutar `install.sh` dentro del workspace.

#### Activación y compilación

Desde Bash, Zsh u otro shell, dentro del nuevo contenedor:

```bash
idf-env                         # abre Bash con ESP-IDF; salir con exit
idf.py --version                 # ESP-IDF v5.5.5
cd /ruta/al/proyecto-idf
idf.py set-target esp32s3        # puede regenerar sdkconfig y limpiar el build
idf.py build
```

También se puede activar por comando, sin modificar el shell padre:

```bash
idf-env idf.py --version
idf-env idf.py set-target esp32s3
idf-env idf.py build
idf-env xtensa-esp-elf-gcc --version
```

`idf-env` usa la activación oficial y propaga sus errores. Abre un Bash sin cargar
archivos de inicio del usuario, o ejecuta el comando recibido. No escribe en
`.bashrc`, `.zshrc` ni archivos globales. Para activar el shell actual Bash/Zsh,
se puede ejecutar `. /opt/esp/idf/export.sh`; la imagen ya define las tres rutas
`IDF_*`. No activar el venv de PlatformIO sobre el de ESP-IDF. El wrapper `pio`
continúa ejecutando `/opt/pio/bin/pio`, incluso dentro de `idf-env`.

PlatformIO administra plataformas y frameworks mediante `platformio.ini` y `pio
run`. ESP-IDF nativo usa CMake, `sdkconfig`, `idf.py` y su Component Manager. El
ESP-IDF instalado aquí no reemplaza el framework descargado por PlatformIO. En
cada proyecto IDF, guardar `dependencies.lock` y las versiones de componentes
para que la reproducibilidad del firmware no dependa sólo de la imagen.

#### USB Serial/JTAG y monitor

Los siguientes comandos se documentan para un proyecto autorizado para flasheo.
**La preparación de este entorno no requiere ejecutarlos sobre la placa.**

```bash
ls -l /dev/serial/by-id/          # elegir el enlace de la placa, si existe
PORT=/dev/serial/by-id/ENLACE_REAL_DE_LA_PLACA
test -r "$PORT" && test -w "$PORT"
idf-env idf.py -p "$PORT" flash
idf-env idf.py -p "$PORT" monitor  # salir con Ctrl+]
```

Si no existe `by-id`, resolver el puerto con `pio device list` y `udevadm info` y
usar el `/dev/ttyACM*` actual. No fijar `/dev/ttyACM0` en el manifest. Distrobox
comparte `/dev` por defecto si no se usa `--unshare-devsys`; el bind del directorio
permite ver nodos nuevos tras reconexiones. `/dev/bus/usb` por sí solo no equivale
al acceso a un puerto TTY en un contenedor Podman genérico. `--group-add keep-groups`
conserva los grupos efectivos del host y requiere el runtime **crun**.

Diagnóstico, primero en el host y luego en el contenedor temporal:

```bash
id
lsusb
ls -l /dev/serial/by-id/ /dev/ttyACM*
udevadm info --query=property --name=/dev/ttyACM0
test -r /dev/ttyACM0 && test -w /dev/ttyACM0
# En el host:
podman info --format '{{.Host.OCIRuntime.Name}}'
podman inspect NOMBRE_DE_INSTANCIA_TEMPORAL --format '{{json .Mounts}}'
```

Comparar presencia, destino del enlace y permisos efectivos; los nombres de grupos
dentro del contenedor pueden diferir aunque el acceso heredado funcione. Cerrar
otros monitores antes de usar el puerto. Si desaparece, reconectar y redescubrirlo.
Si el host no tiene acceso, los paquetes udev de la imagen no corrigen sus ACL o
grupos. Si hay un rechazo SELinux, recopilar el AVC del host antes de proponer un
cambio: esta configuración no modifica políticas, reglas udev ni usa privilegios
adicionales para resolver permisos. Un monitor también puede abrir el puerto y
alterar señales de reset; no forma parte de los tests automáticos.

#### VS Code y ESP-IDF

Adjuntar Dev Containers a una instancia Podman temporal durante la evaluación;
para persistir el trabajo, montar sólo el directorio del proyecto autorizado. Mantener
la configuración de PlatformIO anterior y agregar este perfil de terminal a la
configuración nombrada del contenedor:

```json
{
  "terminal.integrated.profiles.linux": {
    "ESP-IDF 5.5.5": { "path": "/usr/local/bin/idf-env" }
  }
}
```

Abrir el proyecto y seleccionar ese perfil para `idf.py`. Las tasks pueden invocar
`/usr/local/bin/idf-env` con argumentos `idf.py`, `build`. Esta ruta no requiere que
una extensión descargue otro SDK. Si se usa la extensión Espressif, seleccionar
la instalación existente `/opt/esp/idf`, herramientas `/opt/esp` y Python
`/opt/esp/python/bin/python`; no usar su instalación automática. Para IntelliSense,
usar el `build/compile_commands.json` producido por CMake.

#### Waveshare ESP32-S3-ePaper-1.54 V2

La placa **V2** usa ESP32-S3-PICO-1-N8R8 (8 MB Flash y 8 MB PSRAM), pantalla
monocromática 200 × 200 y USB Serial/JTAG. Los ejemplos de V1 y V2 no son
intercambiables, según [Waveshare](https://docs.waveshare.com/ESP32-S3-ePaper-1.54).
Consultar los ejemplos y esquemas **V2** del
[repositorio oficial](https://github.com/waveshareteam/ESP32-S3-ePaper-1.54).

Esta integración sólo compila `hello_world` para `esp32s3`: no define GPIOs, modo
de PSRAM, particiones, alimentación de pantalla ni configuración de periféricos.
Estos parámetros deben derivarse del esquema y ejemplo V2 antes de implementar
InfraBadge. El tamaño de Flash y el modo de PSRAM deben configurarse explícitamente
en el futuro proyecto; el smoke test no certifica un firmware listo para la placa.
No se lee ni se incorpora a Git el backup privado de fábrica. No se flashea, borra
Flash, modifica eFuses ni habilita Secure Boot/Flash Encryption en esta tarea.

#### Reconstrucción, evaluación y rollback

Construir con un tag separado, desde la raíz del repositorio:

```bash
podman build -t localhost/custom/iot-dev:esp-idf-5.5.5 \
  -f dockerfiles/Containerfile.iot-dev .
podman run --rm -i --user 1000:1000 --network none --cap-drop all \
  --security-opt no-new-privileges localhost/custom/iot-dev:esp-idf-5.5.5 \
  bash -s < tests/iot-smoke.sh
podman image inspect --format '{{.Size}}' localhost/custom/iot-dev:esp-idf-5.5.5
```

El smoke test usa un HOME temporal, compila realmente el ejemplo `hello_world`
con FreeRTOS para ESP32-S3 y verifica el ELF Xtensa y los binarios. Comprueba
PlatformIO antes, durante y después de activar IDF, incluyendo `system info`,
`device list` y `pkg list -g`. La enumeración vacía es válida en CI; no demuestra
acceso a una placa real. El build del ejemplo se ejecuta **sin red ni USB y como
UID 1000**, con `/opt/pio` y `/opt/esp` no escribibles para ese UID.

Para evaluar USB sin afectar `iot-dev`, usar Podman rootless directamente con
un puerto resuelto en el momento. No usar `stack.sh deploy/recreate iot-dev`
durante la prueba (`replace=true` en el manifest):

```bash
PORT=$(readlink -f /dev/serial/by-id/ENLACE_REAL_DE_LA_PLACA)
test -c "$PORT" && test -r "$PORT" && test -w "$PORT"
podman run --rm --userns keep-id --group-add keep-groups \
  --device "$PORT:/dev/infrabadge" --device /dev/bus/usb \
  --network none --cap-drop all --security-opt no-new-privileges \
  --env HOME=/tmp/iot-idf-user localhost/custom/iot-dev:esp-idf-5.5.5 \
  bash -ec 'mkdir -p "$HOME"; test -r /dev/infrabadge; test -w /dev/infrabadge;
            idf-env idf.py --version; pio device list'
```

Esto sólo comprueba visibilidad/permisos y herramientas; no abre el puerto ni
flashea. Podman resuelve el nodo al crear la instancia: tras reconexión, redescubrir
el puerto y ejecutar otra instancia temporal. Un rechazo SELinux debe investigarse
con evidencia, sin cambiar políticas ni añadir flags como solución automática.
El HOME está en la capa temporal y desaparece al finalizar. El `iot-dev` existente
continúa usando su imagen anterior; volver a él es el rollback de la evaluación.

**Límite de Distrobox 1.8.2.5:** el `/usr/bin/distrobox-create` inspeccionado en el entorno
local agrega internamente `--privileged` y desactiva el etiquetado del contenedor,
incluso en modo rootless. Esto entra en conflicto con la restricción de esta tarea.
Por eso no se crea una nueva Distrobox ni se ofrece ese flujo como una prueba sin
privilegios. El manifest se conserva, sin ampliar sus flags, para el entorno
existente. La inicialización/recreación Distrobox requiere resolver explícitamente
esa decisión; no se certifica su cumplimiento por el solo hecho de usar rootless.

Después de revisar/mergear el PR y obtener una publicación validada, registrar
el ID/digest de la imagen anterior y protegerlo con un tag local antes de una
recreación expresamente programada. Guardar el estado del proyecto y no borrar
`~/.local/share/platformio`. Probar primero la nueva imagen por digest con Podman;
una futura recreación Distrobox queda condicionada a la decisión anterior. Si se
habilita ese despliegue, actualizar sólo `image=` de `[iot-dev]` al digest probado
y recrear únicamente ese workspace. Para volver atrás, usar el digest/tag guardado
y reutilizar el estado persistente. Los tags locales de build no son los tags GHCR
que consume `stack.sh`. No se ejecuta despliegue ni merge durante esta integración.

ESP-IDF agrega un SDK y compiladores de tamaño considerable. El workflow
`iot-dev-test.yml` mide bytes OCI sin comprimir de candidato y baseline reconstruido
desde la base del PR, duración del build y ocupación de `/opt/esp`/`/opt/pio`. No
confundir esas cifras con descarga comprimida ni espacio exclusivo en disco.
El clon superficial, selección de target y limpieza en la misma capa reducen
tamaño; el orden de capas permite reutilizar APT/PlatformIO con `podman build
--layers` localmente. Si la medición justifica caché en runners efímeros, evaluar
un cache OCI con `--cache-from/--cache-to` en un PR separado; no se altera la
retención ni se publican imágenes de prueba en este cambio.

Validación ejecutada el **15 de octubre de 2026**, sobre el código del commit
`5ccc2a7`, en [GitHub Actions](https://github.com/jnbntc/distrobox-stack/actions/runs/38677329341):
build OCI correcto (149 s), smoke test y compilación ESP32-S3 correctos (35 s),
PlatformIO 6.2.0 correcto y ELF Xtensa verificado. CMake 3.25.1 y Ninja 1.11.1.
El job completo duró 3 min 27 s. Mediciones sin comprimir:

| Imagen | Bytes OCI | Aproximación binaria |
| --- | ---: | ---: |
| Base del PR reconstruida | 287756518 | 274.43 MiB |
| Con ESP-IDF | 4852288162 | 4.519 GiB |
| Incremento | 4564531644 | 4.251 GiB |

`du -sh` dentro de la imagen: `/opt/esp` 4.1G y `/opt/pio` 44M. Es un incremento
considerable que debe aceptarse antes del despliegue. Se conservan las herramientas
requeridas del manifiesto oficial para evitar recortar soporte ULP/depuración.
La caché de capas mejora las reconstrucciones, pero no reduce el tamaño descargado.
Una imagen especializada sólo para compilar, sin GDB/OpenOCD/ROM ELF, sería una
alternativa separada con menor funcionalidad; no reemplaza el entorno completo aquí.
Localmente el build se intentó y quedó bloqueado por el sandbox (`newuidmap`);
no se ejecutaron inicialización Distrobox, hotplug, flasheo ni monitor físico.

Para actualizar dependencias Python, hacerlo en un contenedor Bookworm temporal:
usar `uv 0.13.1 pip compile /opt/esp/idf/tools/requirements/requirements.core.txt`
con un archivo de entrada que agregue `pip` y `wheel`, la snapshot de constraints,
`--python-version 3.11 --python-platform x86_64-manylinux_2_28 --generate-hashes
--no-emit-index-url --no-header --no-annotate`. Guardar en `requirements.lock` y
extraer los bloques completos de `pip`, `setuptools`, `wheel` y `packaging` a `bootstrap.lock`.
Revisar el diff y volver a compilar: el bootstrap fijado permite construir sdists
como esptool con `--no-build-isolation`, sin resolver herramientas de build móviles.
La snapshot de constraints proviene de
`https://dl.espressif.com/dl/esp-idf/espidf.constraints.v5.5.txt`, obtenida el
15 de octubre de 2026, SHA-256
`4839993120d0bdf9757504d402d1a18287e76758cb28d311abc64f2503d11977`.

Problemas comunes: si falla la activación, verificar rutas y `idf-env python -m pip
check`; si se mezclaron SDK/targets, regenerar únicamente el directorio de build
del proyecto y revisar `sdkconfig` antes de `set-target`; si `/opt/esp` no permite
escritura, reconstruir la imagen en lugar de instalar como usuario; si falla una
descarga por hash, investigar el origen y revisar el pin en un PR, nunca omitir
la verificación. Un fallo `newuidmap: Operation not permitted` dentro de un sandbox
no diagnostica el Podman del host: ejecutar el build autorizado desde una terminal
normal o usar el CI.

## android-ops

Workspace rootless dedicado a administración y diagnóstico de dispositivos Android por USB. Usa el paquete `android-tools` de Fedora, que aporta `adb` y `fastboot`, además de `usbutils` y `jq` para inventario y scripts de auditoría.

El acceso USB sigue el mismo patrón que `iot-dev` y `books-ops`:

```ini
additional_flags="--device /dev/bus/usb:/dev/bus/usb:rwm --group-add keep-groups"
```

Flujo básico:

```bash
./scripts/stack.sh pull android-ops
./scripts/stack.sh deploy android-ops
distrobox enter android-ops

adb version
fastboot --version
lsusb
adb devices
```

Para que ADB vea un teléfono real, la depuración USB debe estar habilitada y autorizada en Android, y el usuario del host debe tener permisos sobre el dispositivo USB. Las reglas/permisos udev pertenecen al host, no a la imagen OCI.

El workspace se usa para auditoría y mantenimiento; no exporta `adb` ni `fastboot` al host.

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

`.github/workflows/ghcr-publish.yml` construye y publica semanalmente y ante cambios en Containerfiles/scripts. Además ejecuta smoke tests básicos para los workspaces críticos, incluyendo PlatformIO/USB en `iot-dev` y ADB/Fastboot en `android-ops`.

`iot-dev` ejecuta además el smoke test offline completo anterior antes de publicar.
`.github/workflows/iot-dev-test.yml` construye sólo `iot-dev` en los PR relevantes,
sin autenticación GHCR ni permisos de publicación, y mide el incremento de tamaño.
Las pruebas físicas USB y la inicialización Distrobox se mantienen separadas del CI.

`.github/workflows/maintenance.yml` aplica una política de retención semanal:

- conserva los **10 runs completados más recientes** por workflow;
- conserva las **3 versiones más recientes** de cada imagen activa en GHCR, protegiendo además cualquier versión etiquetada como `latest`;
- elimina las versiones restantes del paquete obsoleto `media-ops`.

Esto mantiene capacidad de rollback sin acumular indefinidamente tags SHA ni historial de Actions.

## Almacenamiento

Podman rootless y rootful se mantienen fuera del filesystem principal bajo `/var/mnt/storage`. Mantener los contextos SELinux adecuados en esos graphroots.
