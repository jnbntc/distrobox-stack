# trustforge-dev — definición canónica (TF-003, propuesta)

Responsabilidad de este directorio: receta OCI, herramientas del workspace, plantilla Distrobox y mantenimiento de `trustforge-dev`.
Consumidor: [TrustForge, issue #3](https://github.com/jnbntc/trustforge/issues/3).
Estado: validación estática; sin build, publicación, creación ni prueba de ejecución. Revisar ambas PR antes de autorizar despliegue.

## Encaje en el stack real
El stack actual tiene nueve imágenes, un manifest global `distrobox.ini`, un orquestador `scripts/stack.sh`, Containerfiles en `dockerfiles/` y publicación GHCR desde Actions.
El publicador existente se activa por cron semanal, dispatch y push a main/master con filtros dockerfiles/scripts/tests; usa una matriz explícita de nueve imágenes, tags latest/SHA y smoke tests. No genera explícitamente SBOM, firmas Cosign ni provenance autenticada. No se atribuye un nivel SLSA.
La limpieza existente retiene tres versiones por imagen y latest, y opera sobre una lista explícita; trustforge-dev no entra en esa limpieza.

Este workspace queda **optativo**, con una receta única fuera de los directorios de publicación masiva. `distrobox.ini`, `scripts/stack.sh`, Makefile, imágenes existentes y workflows existentes no se modifican. Es una excepción de ubicación deliberada: agregar el Containerfile bajo dockerfiles habría activado la publicación de las nueve imágenes al integrar un cambio. El nuevo workflow no tiene push, pull_request, schedule, workflow_call ni repository_dispatch. Una rama de propuesta y su PR no construyen ni publican trustforge-dev; el linter global existente sí puede ejecutarse, sin publicación.

## Fuentes y pins
[contract.json](contract.json) es el inventario canónico de pins y límites. No editar versiones en TrustForge como segunda definición; actualizar contrato, receta y lock juntos mediante PR.

| Elemento | Pin verificado por consulta de metadatos |
|---|---|
| Fedora Toolbox | 44, linux/amd64; manifiesto `sha256:2b94f5ab65312e97c3ac02820fcd67fde07024bc2ca052c1f9e27ff2692c4596` |
| uv | 0.13.6; manifiesto amd64 `sha256:8b7774a14bb3abde914fda03efcb83f1f7e9163124e5c13e7fb4cc825293f5fa` |
| CPython gestionado por uv | 3.13.18, build python-build-standalone 20261026; URL y SHA-256 en contrato |
| Herramientas | pytest 9.2.0, Ruff 0.17.3, mypy 1.20.2; once paquetes transitivos fijados con hashes |
| Utilidades RPM | ca-certificates, curl, Git, jq y Skopeo desde Fedora; versiones efectivas pendientes del build |

El 27-10-2026 se leyeron índices/manifiestos por HTTPS y se verificó el hash de sus bytes contra cabecera y descriptor. No se descargaron capas; eso comprueba integridad direccionada por contenido, no identidad criptográfica del publicador ni compatibilidad de ejecución.
Python se contrastó con los metadatos de [uv 0.13.6](https://github.com/astral-sh/uv/releases/tag/0.13.6), que incorpora 3.13.18, y con la [release de Python](https://www.python.org/downloads/release/python-31318/). No se descargó ni ejecutó el intérprete.
El contrato conserva también los digests de los índices, distintos de los manifiestos amd64 fijados en FROM.

El lock se resolvió con uv 0.13.5, sin instalar paquetes ni intérpretes:
```bash
UV_CACHE_DIR=/ruta/scratch/uv uv pip compile --python-version 3.13.18 \
  --python-platform x86_64-manylinux_2_28 --no-python-downloads \
  --only-binary :all: --generate-hashes --no-emit-index-url \
  --no-header --no-annotate workspaces/trustforge-dev/requirements.in \
  --output-file workspaces/trustforge-dev/requirements.lock
```
El resolver avisó que 3.13.18 no estaba disponible localmente y usaría 3.12.15 para builds de dependencias; la resolución se restringió a binarios y no se ejecutaron builds de sdists. Los marcadores y destino solicitados fueron 3.13.18/linux x86_64. No equivale a una prueba de instalación del lock.

## Python, HOME, checkout y persistencia
- Python del sistema/host no se reemplaza. El intérprete gestionado vive en /opt/trustforge/python y se expone como trustforge-python; uv lo selecciona mediante UV_PYTHON. Se deshabilitan nuevas descargas de intérpretes en runtime.
- pytest/Ruff/mypy viven en un venv de herramientas root-owned dentro de la imagen. Las dependencias de la aplicación y su .venv pertenecen a TrustForge TF-004 y no se duplican aquí.
- HOME propuesto: ~/.local/share/trustforge-dev/home. Cachés: ~/.cache/trustforge-dev, con uv bajo uv/. Se persisten fuera de la capa del contenedor. No hay instalaciones en el HOME principal ni exports de binarios al host.
- Único bind explícito de proyecto: ~/Proyectos/trustforge -> /workspace/trustforge:rw, sin :z/:Z ni cambios de etiquetas. No se usa el checkout de otro workspace.
- Sin motor anidado ni wrappers de ejecución en host. Skopeo es cliente OCI; Podman se usa desde una terminal del host para pruebas futuras autorizadas, no mediante socket montado o host-exec.
- No se configura graphroot: Podman mantiene su almacenamiento rootless existente. No se modifica storage.conf, servicios, grupos ni SELinux. La ocupación real es pendiente; no se deduce de los GB libres informados.

## Bloqueo de despliegue: integración y privilegios implícitos
La plantilla no agrega dispositivos, capacidades, sockets ni host networking; usa root=false, replace=false, pull=false, start_now=false, init=false y unshare_all=true.
Eso **no convierte Distrobox en un sandbox**. Se inspeccionó [distrobox-create 1.8.2.5](https://github.com/89luca89/distrobox/blob/40c3cd724faa434aeb0a23e28776665b92de68bd/distrobox-create#L686): añade --privileged, label=disable, apparmor=unconfined y root dentro del user namespace. También comparte HOME y /run/user cuando corresponde, aunque se elija HOME dedicado; los sockets de sesión o un socket de motor existente podrían resultar visibles por esa integración.
unshare_all reduce compartición de namespaces/dispositivos, pero no elimina esos flags ni todos los montajes. El host puede seguir en SELinux Enforcing mientras el etiquetado del contenedor está desactivado: no se presenta como confinamiento SELinux.
Por tanto **crear/entrar no cumple todavía una garantía de ausencia de privilegios o sockets heredados**. No se ofrece una excepción automática ni se cambia Distrobox para sortearlo. Requiere revisión arquitectónica: aceptar explícitamente la integración para desarrollo confiable, evaluar una versión/configuración que la limite con evidencia, o proponer otro consumidor en un ADR separado. No se declara ninguna alternativa validada.

## Construcción/publicación futura: manual y sin despliegue
[Workflow dedicado](../../.github/workflows/trustforge-dev.yml): dispatch desde main, build linux/amd64, archivo OCI candidato con checksum, y job de publicación solo si publish=true.
El job de build solo tiene contents:read; packages:write queda en el job de publicación. Acciones fijadas por SHA; el checkout no conserva credenciales. No hay id-token:write ni firmas en esta iteración. Solo se publica ghcr.io/jnbntc/trustforge-dev con tag del commit; no latest ni actualizaciones de otras imágenes.
No ejecutar dispatch, builds ni publicación durante la revisión. Un digest de salida aún no existe. Una futura publicación candidata no autoriza su uso.
El workflow comprueba la receta estáticamente, pero no ejecuta smoke tests del contenedor: añadirlos y medir tamaño/red/SELinux forma parte de la autorización posterior.

Reproducibilidad: pins de fuentes y lock Python están declarados; los RPM y parte de la inicialización de Distrobox siguen resolviéndose contra repositorios móviles. Se emite /usr/share/trustforge/rpm-packages.txt como inventario; no es SBOM ni snapshot. No se promete build idéntico entre fechas. Para repetir el despliegue se necesitará la imagen final verificada por digest; para reconstrucción estricta, snapshot RPM/inicialización controlada y una prueba de dos builds.

## Supply chain progresiva y verificación previa al despliegue
| Capacidad | Stack actual / esta propuesta | Pendiente antes del despliegue definitivo |
|---|---|---|
| Imagen base | Pin por digest verificado; otros workspaces tienen estrategia mixta | Revisar identidad/origen de base y actualizaciones |
| Herramientas | uv/Python fijados, lock de devtools con hashes | Build e instalación reales; inventario RPM y snapshot si se exige rebuild exacto |
| Imagen final | Workflow manual candidato, sin ejecución | Construir, probar y registrar digest |
| SBOM | No implementada por el publicador actual ni aquí | Generar SPDX/CycloneDX por digest con herramienta fijada; autenticar y verificar asociación |
| Firma Cosign | No implementada | Aprobar identidad OIDC exacta, issuer y trust roots; firmar y verificar digest |
| Provenance | No se emite atestación de builder | Elegir mecanismo soportado, autenticar subject/source/builder; documentar límites |
| Gate de despliegue | Renderer valida formato; NO verifica confianza | Verificador fail-closed de imagen/evidencias autorizadas antes de cualquier pull/create |

No se fabrica una atestación a partir de un JSON de inventario ni se atribuyen garantías SLSA. Cambios de identidades, raíces o workflows de firma requieren aprobación separada.

## Procedimiento de despliegue — NO ejecutar todavía
1. Revisar ambas PR; resolver el bloqueo Distrobox y aprobar build, publicación y pruebas, cada uno con su alcance. Merge no es permiso para dispatch.
2. Construir solo este candidato con el workflow manual o la receta explícita; revisar logs, toolchain, inventario RPM, ocupación y vulnerabilidades/evidencias disponibles. No usar stack.sh ni make para esta evaluación.
3. Completar/autorizar SBOM, firma y provenance; verificar identidad, issuer, subject y digest final. No consumir un tag mutable ni el digest de la base como si fuera el workspace.
4. Desde el host real, con permiso para consultas de runtime, comprobar ausencia del nombre trustforge-dev y registrar recursos existentes. Si existe, detenerse: no reemplazar.
5. Revisar acceso/escrituras del checkout y los directorios dedicados. Después de verificar imagen y permisos, renderizar un único manifest por digest:
```bash
python3 -B workspaces/trustforge-dev/render-manifest.py \
  --image ghcr.io/jnbntc/trustforge-dev@sha256:DIGEST_VERIFICADO_DE_64_HEX \
  > /ruta/privada/trustforge-dev.ini
```
El marcador se rechaza: debe sustituirse por el digest real. El renderer no usa Podman, no escribe archivos salvo la redirección decidida por el operador y no comprueba firmas. No es un gate de seguridad. Rutas con espacios o sintaxis de shell se rechazan.
6. Solo tras todas las aprobaciones, descargar esa imagen por digest y usar el manifest privado con distrobox assemble create --file ... --name trustforge-dev. Primer enter y pruebas se autorizan como cambios, aunque start_now=false. No ejecutar el manifest global.
7. Registrar resultado de creación, imagen exacta, mounts, flags reales, estado del checkout, herramientas y pruebas negativas. No cerrar TF-003 hasta reproducibilidad/pruebas/revisión completas.

Rollback limitado: registrar antes los recursos nuevos; detener y retirar únicamente trustforge-dev si fue creado por esta intervención. Conservar checkout y evidencia. HOME/cachés dedicados no se borran automáticamente; revisar y retirar solo archivos nuevos prescindibles. Quitar la imagen solo si se incorporó aquí y no la usa otro contenedor. Nunca prune/reset, borrar graphroot, recrear el stack, restaurar HOME a ciegas ni tocar workspaces existentes. Borrar el contenedor no revierte escrituras en el checkout ni montajes compartidos.

## Validación estática
```bash
python3 -B workspaces/trustforge-dev/validate-static.py
```
Pruebas de pins y hashes, separación del manifest global, opciones explícitas y rechazo de tag mutable/repositorio ajeno/digest inválido/rutas con inyección. No llama motores ni instala herramientas.
La validación de YAML y bloques shell del workflow se ejecuta aparte con herramientas ya disponibles durante la revisión. Hadolint/ShellCheck/actionlint no estaban instalados en el ejecutor; no se instalaron. El linter global solo cubre sus rutas originales.

## Decisiones pendientes
Aprobar la integración/privilegios implícitos de Distrobox, accesos reales del HOME/runtime, base/toolchain fijadas, alcance de build/publicación, pruebas funcionales y recursos de rollback. Fijar inventario/snapshot RPM y completar evidencias autenticadas antes de declarar el entorno reproducible y listo.
