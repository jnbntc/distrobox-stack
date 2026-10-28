# trustforge-dev — workspace de desarrollo confiable

TF-003 · definición canónica de [distrobox-stack PR #18](https://github.com/jnbntc/distrobox-stack/pull/18).
Consumidor: [TrustForge PR #30](https://github.com/jnbntc/trustforge/pull/30).
Estado: propuesta corregida para revisión. Sin build, publicación, firma real ni creación del entorno.

## Modelo de seguridad aceptado para la propuesta
trustforge-dev se utiliza exclusivamente para desarrollo y pruebas con código confiable. **No es un sandbox de seguridad** y no se usa para ejecutar imágenes o artefactos adversarios no confiables.
Podman rootless limita el alcance al usuario del host; no elimina los privilegios dentro del user namespace ni la integración de Distrobox.

La fuente de [Distrobox 1.8.2.5](https://github.com/89luca89/distrobox/blob/40c3cd724faa434aeb0a23e28776665b92de68bd/distrobox-create#L686) añade --privileged, --security-opt label=disable, apparmor=unconfined y usuario root dentro del contenedor para inicializarlo. El HOME original y /run/user pueden seguir montados, incluso con HOME dedicado; por tanto sockets de sesión/usuario, incluido un motor si existe allí, podrían ser visibles.
unshare_all reduce compartición de namespaces/dispositivos; no elimina esas opciones ni todos los montajes. SELinux Enforcing en el host no implica confinamiento por etiquetas del contenedor si label=disable está activo.
Estas conclusiones provienen de inspección del código de esa versión, no de ejecutar create/inspect en este host. Mounts, visibilidad de sockets y flags efectivos del futuro contenedor permanecen pendientes de prueba autorizada.
No se agregan flags explícitos de capacidades/dispositivos/sockets, no se cambia SELinux y no se ofrece esa omisión como aislamiento fuerte.

### Frontera independiente para M4
Los escenarios adversarios de M4 no reutilizarán trustforge-dev. Se diseñará por separado un runtime con restricciones explícitas para casos de bajo riesgo; se usarán VMs desechables cuando el riesgo/aislamiento lo justifique. No compartir HOME, sockets o credenciales con un laboratorio adversario por conveniencia. Criterios de aislamiento y aceptación propios antes de ejecutar esos escenarios. No se implementa M4 en estas PRs.

## Encaje en el stack existente
El stack conserva sus nueve imágenes, distrobox.ini, scripts/stack.sh, Makefile y los cuatro workflows anteriores. No se modifican sus bytes, listas de publicación/retención ni mecanismos de despliegue.
Este directorio es optativo: mantenerlo fuera de dockerfiles/scripts/tests evita que su integración active el publicador masivo. El README raíz solo enlaza esta definición.

La nueva cobertura específica usa [trustforge-static.yml](../../.github/workflows/trustforge-static.yml): pull_request filtrado por esta ruta y los dos workflows dedicados, permisos contents:read, sin paquetes, OIDC, installs, motores o publicación.
[trustforge-dev.yml](../../.github/workflows/trustforge-dev.yml) sigue siendo exclusivamente workflow_dispatch, main-only, publish=false por defecto. Los dos documentos usan JSON válido como subconjunto estricto de YAML para análisis estructural con la biblioteca estándar, sin instalar un parser.

## Contrato de herramientas y fuentes
[contract.json](contract.json) y el [lock](requirements.lock) son la fuente canónica. TrustForge no contiene otra receta/manifest/lock del workspace.

| Fuente | Pin conservado |
|---|---|
| Fedora Toolbox 44 linux/amd64 | sha256:2b94f5ab65312e97c3ac02820fcd67fde07024bc2ca052c1f9e27ff2692c4596 |
| uv 0.13.6 linux/amd64 | sha256:8b7774a14bb3abde914fda03efcb83f1f7e9163124e5c13e7fb4cc825293f5fa |
| Python gestionado | CPython 3.13.18, build 20261026; URL/SHA-256 en contrato |
| Devtools | pytest 9.2.0, Ruff 0.17.3, mypy 1.20.2; once paquetes fijados con hashes |

Los índices/manifiestos se comprobaron el 27-10-2026 por hash de bytes, cabecera y descriptor, sin descargar capas; Python se contrastó con los metadatos oficiales de uv. Se mantienen esos pins sin reconsultarlos en esta corrección.
El lock se resolvió con uv 0.13.5 para 3.13.18/x86_64-manylinux_2_28 y solo binarios, sin instalación. Hubo aviso de intérprete local 3.13.18 ausente y fallback 3.12.15 para builds de dependencias; no se construyeron sdists. No equivale a una prueba de instalación.

Python vive bajo /opt/trustforge/python; trustforge-python y UV_PYTHON seleccionan el gestionado sin reemplazar /usr/bin/python3 ni el Python del host. Las herramientas viven en un venv root-owned de la imagen; las dependencias de aplicación/.venv pertenecen a TF-004.
El HOME dedicado propuesto es ~/.local/share/trustforge-dev/home; cachés ~/.cache/trustforge-dev. Bind de proyecto explícito: ~/Proyectos/trustforge -> /workspace/trustforge:rw, sin :z/:Z. No representa una lista exhaustiva de mounts de Distrobox.
Sin motor anidado ni host-exec; Skopeo inspecciona OCI. Se conserva graphroot/configuración rootless existente, sin cambios en storage.conf, servicios, permisos o workspaces anteriores.

## Bootstrap independiente: sin dependencia circular con M3
La aceptación inicial usa [verify-bootstrap.py](verify-bootstrap.py), Python estándar en un entorno ya confiable y **Cosign independiente fijado**, antes de entrar a trustforge-dev. No importa TrustForge Gate ni necesita la CLI de M3.
El [procedimiento exacto](BOOTSTRAP.md) cubre política externa revisada, raíces, digest final, firma/identidad/issuer, SBOM y provenance vinculadas al subject, parámetros esperados y aprobación humana.
La [interfaz de Cosign 3.1.4](COSIGN_INTERFACE.md) exige firma dedicada con el tipo nativo sign/v1, separada de SPDX/provenance y con anotación firmada de repositorio. No acepta proyecciones critical.* como sustituto. La regresión se reprodujo con mocks: no demuestra ruptura criptográfica de Cosign ni interoperabilidad real con GHCR.
La plantilla [trust-policy.example.json](trust-policy.example.json) está approved=false, sin source commit ni hash de raíz. No existen certificados/evidencias reales de esta imagen y no se inventan. El renderer solo valida formato de manifest, no confianza.

El futuro workflow prepara:
1. Build de una sola imagen y registro de source/workflow/run después del build correcto, sin privilegios de publicación.
2. Job separado de publicación/firma con packages:write y id-token:write, únicamente con publish=true desde main; entorno trustforge-bootstrap-publish pendiente de configurar/proteger por un humano.
3. Push de la imagen y captura de su digest, Syft fijado sobre esa referencia por digest, firma Cosign keyless, atestación SPDX y provenance custom vinculadas al mismo digest.
4. Artefactos de diagnóstico; su mera presencia no demuestra autenticidad. Un fallo después del push puede dejar un candidato sin evidencias completas: el verificador lo deniega.

Cosign 3.1.4 y Syft 1.55.0/acciones oficiales están fijados en contrato; no se instalaron ni ejecutaron ahora. La provenance es una declaración del workflow autenticada si la firma futura tiene éxito; no es evidencia de builder independiente ni nivel SLSA.

## Garantías distintas y estado actual
| Garantía | Significado | Estado |
|---|---|---|
| Integridad | Digest identifica bytes | Fuentes OCI/lock comprobados; imagen final ausente |
| Autenticidad | Firma y certificado de identidad/issuer autorizados | Código preparado; pendiente firma/verificación real |
| Provenance | Origen, workflow, commit, materiales y parámetros autenticados | Generador/verificador preparados; datos reales pendientes |
| Repetibilidad del despliegue | Consumir la misma imagen final aprobada por digest | Pendiente digest final, verificación y creación |
| Reproducibilidad de construcción | Reconstruir resultados equivalentes/idénticos bajo criterio definido | No demostrada: repos RPM e inicialización móviles |

El inventario /usr/share/trustforge/rpm-packages.txt no fija un snapshot ni sustituye una SBOM. La autenticidad de una firma no prueba ausencia de vulnerabilidades ni corrección del builder. Un workflow/builder autorizado comprometido permanece como riesgo. No se promete igualdad byte por byte entre builds.

## Validación específica
```bash
python3 -B workspaces/trustforge-dev/validate-static.py
```
Sin dependencias externas ni consultas de red: lint estructural del Containerfile, bash -n de RUN y workflows, AST de scripts, JSON/INI, lock/hash, pins, rutas/permisos/eventos y casos negativos del bootstrap.
Las fixtures de salida Cosign son simuladas y están etiquetadas como tales. No son firmas ni verificación criptográfica real.
Se cubren ausencia/sustitución de firma dedicada, identidad rechazada por Cosign simulado, duplicados/malformación y fallo de cualquiera de las tres comprobaciones.
El nuevo CI ejecuta estos mismos checks sobre la ruta específica. El linter global previo no se modifica ni se presenta como cobertura nueva de este Containerfile. No se ejecutó Hadolint/ShellCheck/actionlint localmente ni se instaló ninguno.

## Despliegue y rollback — pendientes de autorización nueva
Revisar ambas PRs y la política/identidades/raíces; no inferir permiso de ejecución del merge.
Separar autorizaciones: build candidato; publicación y generación de evidencias; verificación independiente con política aprobada; despliegue.
Después de verificación real satisfactoria, solicitar aprobación humana explícita para ese digest exacto. Solo entonces comprobar colisiones y estado previo, renderizar manifest individual, descargar por digest y crear/inicializar exclusivamente trustforge-dev. No usar stack.sh, make ni el manifest global para este entorno.
Las pruebas autorizadas deberán registrar mounts/flags reales, rootless, acceso/persistencia de checkout, herramientas, red y efectos de Distrobox/SELinux. No ejecutar artefactos adversarios aquí.
Rollback: detener/eliminar solo el nuevo trustforge-dev si fue creado en esa intervención; conservar checkout/evidencia, revisar HOME/cachés antes de quitar archivos propios y retirar una imagen solo si es nueva/no compartida. Nunca prune/reset, borrar graphroot ni recrear otros workspaces. Borrar el contenedor no revierte escrituras del checkout/HOME.
