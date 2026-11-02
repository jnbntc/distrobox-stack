# Bootstrap provisional de confianza — independiente de TrustForge Gate

Estado: código/workflow preparados; **sin build, publicación, firma o verificación criptográfica real de trustforge-dev**.
Este procedimiento no necesita M3. Se ejecuta desde una copia del código revisada y fijada por commit, en un entorno ya confiable, antes de crear/entrar al workspace.

## 1. Anclas de confianza y aprobación previa
El operador debe disponer de Python estándar y Cosign v3.1.4 obtenido por un canal independiente y autorizado, fuera de la imagen a verificar. La acción oficial fijada prepara Cosign en un futuro job; no instala nada en el host en esta tarea.
El SHA-256 linux/amd64 esperado de Cosign está en contract.json (metadata de release oficial; binario no descargado en esta corrección). Ese hash identifica el binario; su aprobación y la confianza en su canal de distribución son parte de la revisión, no autenticidad derivada del mismo digest de la imagen.

Proveer un Sigstore TrustedRoot JSON auténtico por un canal independiente: distribución Sigstore pública verificada por TUF o paquete de confianza ya aprobado. La adquisición/actualización, procedencia y revisión de esas raíces requieren autorización. No descargar un root adjunto por el publicador de la imagen y aceptarlo por su propio checksum. No hay una raíz privada, certificado o clave inventada en este repositorio.
Registrar el SHA-256 real del archivo de raíces revisado en una copia privada de la política. El verificador exige ese archivo explícito y su hash exacto; no usa un trust root recibido de las evidencias ni desactiva tlog/SCT/claims.

Copiar trust-policy.example.json fuera del checkout público y completar solamente después de revisión humana:
- approved: true, para la política de verificación; no significa autorización de despliegue.
- source_commit: commit de 40 hex de distrobox-stack revisado para ese futuro build. Obtenerlo desde la revisión/source de confianza, no confiar en el commit que diga una atestación.
- trusted_root_sha256: hash real de las raíces aprobadas, sin marcadores.
Mantener issuer/identity/repository/ref/trigger exactos que siguen. La copia externa evita la autorreferencia de intentar incluir el SHA de un commit dentro de ese mismo commit.

## 2. Identidades y política propuestas — pendientes de aprobación
| Campo | Valor candidato derivado del workflow preparado |
|---|---|
| Issuer keyless | https://token.actions.githubusercontent.com |
| Certificate identity/SAN | https://github.com/jnbntc/distrobox-stack/.github/workflows/trustforge-dev.yml@refs/heads/main |
| Repository | jnbntc/distrobox-stack |
| Ref | refs/heads/main |
| Trigger | workflow_dispatch |
| Workflow/source SHA | commit exacto revisado para el build, pendiente |
| Builder declarado | misma URI del workflow; comprobar contra política externa |
| Imagen permitida | ghcr.io/jnbntc/trustforge-dev@sha256:<digest final real> |
| Raíces | TrustedRoot Sigstore independiente revisado; archivo/hash pendientes |
| Environment de publicación | trustforge-bootstrap-publish; protección/revisores pendientes de configuración humana |

Estas son restricciones esperadas propuestas, **no observaciones de un certificado que ya exista**. No hay regex de identidad/issuer, trust-on-first-use, claves provisionales ni allowlist de cualquier workflow.
El propietario debe aprobar identidad, issuer, raíces, permisos OIDC/packages y entorno protegido antes de la publicación/firma. Declarar un environment en YAML no crea por sí solo una protección de revisores; no se cambió esa configuración.

## 3. Generación futura — separar build de publicación
1. Tras revisión y autorización de build, workflow_dispatch desde main con publish=false. Construye solamente trustforge-dev, fija label de revision y crea archivo OCI/checksum y registro de build con source/workflow/run.
2. Para publicación/firma, una autorización independiente permite un dispatch con publish=true. El workflow actual reconstruye el candidato en ese run antes de publicar: autorizar este segundo dispatch implica también ese build; no se reutiliza silenciosamente un archivo de otro run.
3. El publisher main-only verifica checksums y la coherencia del registro con su source/workflow/run, hace push del candidato y captura el digest final.
4. Syft 1.55.0 escanea registry:<imagen@digest> sin ejecutarla; genera SPDX 2.3. Cosign 3.1.4 crea una firma dedicada en formato nuevo con anotación firmada io.trustforge.repository y atesta por separado SBOM/provenance sobre esa referencia.
5. Si falla SBOM/firma/atestación tras el push, la imagen puede existir pero no es aceptable para despliegue. No sustituir las evidencias faltantes por JSON manual ni omitir verificaciones.

Provenance URI: https://github.com/jnbntc/distrobox-stack/workspaces/trustforge-dev/provenance/v1.
Incluye source repository/ref/commit, identidad y SHA de workflow, invocation run/attempt, plataforma/receta/repositorio de imagen, base/uv por digest, hash Python y lock. make-provenance.py se invoca después del build correcto, y el publisher exige el mismo registro/contexto.
Es una declaración del workflow firmante sobre su build. No es un builder independiente ni una certificación SLSA. El runner/CI y el código del workflow aprobado forman parte de la confianza.

## 4. Verificación exacta, fuera del workspace
Requisitos pendientes: imagen final publicada por digest, política externa revisada/completa, Cosign confiable del hash esperado y TrustedRoot auténtico de hash aprobado.
El siguiente es el procedimiento ejecutable; las rutas se sustituyen por archivos reales del operador:
```bash
python3 -B /checkout-revisado/workspaces/trustforge-dev/verify-bootstrap.py \
  --image 'ghcr.io/jnbntc/trustforge-dev@sha256:DIGEST_FINAL_REAL_DE_64_HEX' \
  --policy /ruta/privada/trust-policy.approved.json \
  --cosign /ruta/independiente/cosign \
  --trusted-root /ruta/independiente/trusted_root.json \
  > /ruta/privada/trustforge-bootstrap-verification.json
```
El marcador de digest se rechaza. La política entregada en el repositorio también se rechaza mientras esté approved=false o falten commit/raíz. No hay modo skip-crypto, modo offline-JSON ni auto-install.

El script calcula hash del binario/raíces y llama a Cosign en tres pasos:
1. verify-attestation --type https://sigstore.dev/cosign/sign/v1, para la firma dedicada de imagen.
2. verify-attestation --type spdxjson, sobre la misma imagen.
3. verify-attestation --type <URI de provenance anterior>, sobre la misma imagen.

Los tres comandos exigen --certificate-identity, --certificate-oidc-issuer, --certificate-github-workflow-repository, --certificate-github-workflow-ref, --certificate-github-workflow-sha y --certificate-github-workflow-trigger exactos; --trusted-root explícito, --check-claims=true, --insecure-ignore-tlog=false y --insecure-ignore-sct=false.
Cosign realiza la criptografía, validación de certificados/transparencia y asociación del digest. Se inspeccionaron opciones/salidas de v3.1.4 para preparar este adaptador; su interoperabilidad real sigue pendiente de prueba.

Solo tras un exit 0 de cada comando se interpreta su stdout:
- Firma dedicada: in-toto v1, predicateType https://sigstore.dev/cosign/sign/v1, predicate vacío, digest exacto y anotación firmada io.trustforge.repository igual al repositorio esperado. El subject nativo puede carecer de name; no se confía en un nombre sintetizado por verify.
- Atestaciones: DSSE/in-toto esperado, predicate type y un solo subject del repositorio/digest exactos.
- SBOM: documento SPDX no vacío; la firma autentica su asociación, no demuestra cobertura perfecta ni ausencia de vulnerabilidades.
- Provenance: artefacto, source commit/repository/ref, builder/workflow/SHA/trigger, invocation y parámetros/materiales iguales al contrato aprobado.
Falta/error/timeout, política sin aprobar, raíz/herramienta de otro hash, certificado o sujeto incorrectos, datos malformados/duplicados y evidencias ausentes producen DENY/no éxito, sin fallback. No se interpreta un archivo JSON arbitrario como evidencia verificada.

## 5. Aprobación humana y consumo
VERIFIED significa que pasaron estos controles bajo esas anclas y política; el reporte siempre indica deployment_authorized=false. No es un permiso de despliegue ni un token que deba aceptarse desde un canal no confiable.
Revisar imagen/digest, source commit, root/policy hashes y evidencias de la corrida. Pedir una autorización nueva y explícita para crear trustforge-dev con **ese mismo digest**. Repetir la verificación si cambia el artefacto o la política; nunca volver a resolver un tag para consumirlo.
Después de esa autorización, comprobar colisión/inventario, renderizar el manifest con la referencia verificada y aplicar el procedimiento individual del README. El renderer no reemplaza este procedimiento ni concede confianza por sí mismo.
No verificar desde el contenedor que se pretende aceptar ni ejecutar su contenido para «demostrar» confianza. El laboratorio M4 tiene otra frontera independiente.

## 6. Límites y pruebas pendientes
La [interfaz y fuente oficial](COSIGN_INTERFACE.md) explican por qué critical.* de cosign verify no basta para distinguir firma/SBOM/provenance. Se usan tres comprobaciones nativas tipadas; sin firma dedicada se deniega aunque existan SBOM y provenance. No se aceptan arrays genéricos, duplicados o formatos legacy como fallback.

Se ejecutaron pruebas estáticas y fixtures con Cosign simulado: prueban errores/parámetros/parsers, no criptografía real.
El candidato del run 41344731623 (intento 1, artifact 13098563945, source 89b4ca3b159914fc9e8cb60853907d57cfe9f406) fue construido e inspeccionado sin publicación. Faltan publicación autorizada, firmas/atestaciones reales y negativos reales de identidad/issuer/subject/source; comprobar compatibilidad GHCR/referrers/formato; probar mounts/SELinux y persistencia con Distrobox autorizado.
RPM móviles e inicialización no fijada siguen limitando rebuilds. Integridad, autenticidad, provenance, repetibilidad de consumo por digest y reproducibilidad de build son garantías distintas; ninguna es equivalente a que una receta exista.
Referencias: [Cosign verify](https://docs.sigstore.dev/cosign/verifying/verify/), [atestaciones](https://docs.sigstore.dev/cosign/verifying/attestation/), [Cosign v3.1.4](https://github.com/sigstore/cosign/tree/v3.1.4).

## 7. Promoción del candidato inspeccionado, sin reconstrucción

`trustforge-promote.yml` es un workflow manual separado. El run 41380381655
publicó el manifiesto inspeccionado, pero quedó INCOMPLETE / NOT VERIFIED al
fallar la subida de la firma Cosign con UNAUTHORIZED; las atestaciones no se
ejecutaron. No se autoriza despliegue por ese resultado parcial.
El workflow de build original permanece intacto. Su opción `publish=true`
**reconstruye** y no sirve para promover este candidato exacto.

`promotion-candidate.json` fija repositorio/ID, run/intento, artifact/ID, source,
ZIP/tar/build-record hashes, plataforma, manifiesto/configuración y base Fedora.
Cambiar el candidato requiere otra revisión; no hay inputs de repositorio, run,
artifact o digest arbitrarios. La confirmación exacta se obtiene localmente con:

```bash
python3 -B workspaces/trustforge-dev/promote-candidate.py confirmation
```

Antes de ejecutar la promoción se requiere autorización explícita nueva y main
revisado. El job `validate` solo dispone de `contents: read` y `actions: read`:
contrasta metadata GitHub de origen (build exitoso, publish omitido), descarga el
artifact por ID, comprueba los bytes completos y valida el OCI sin ejecutar código
de la imagen. Extrae del ZIP únicamente los tres archivos esperados y rechaza
duplicados, rutas extras, enlaces y tamaños inesperados.

El job `publish` depende de ese resultado y del environment
`trustforge-bootstrap-publish`, vuelve a validar el ZIP original transferido por
artifact ID del run actual y solo entonces recibe credenciales en el paso de
publicación. `skopeo copy --preserve-digests` copia el OCI archive; no lo carga ni
lo reconstruye. Se exige el manifiesto inspeccionado tanto en el digest de salida
como al leerlo por digest desde GHCR. SPDX se genera sobre el mismo archive local.
Firma dedicada y dos atestaciones se vinculan a esa referencia inmutable.
Los re-runs del promotor se deniegan; un fallo requiere revisión humana antes de
otro dispatch. Una interrupción después del push puede dejar una imagen sin todas
las evidencias: no supone aceptación ni despliegue; revisar la evidencia conservada.

La identidad del promotor es distinta de la del builder. La política externa
existente **no autoriza esa identidad nueva**. `promotion-policy.example.json`
introduce el esquema 2 y permanece `approved=false`: `source_commit` es el commit
original del candidato; `signer_commit` debe ser el commit real del workflow de
promoción revisado en main, aprobado por el propietario junto con la identidad
`trustforge-promote.yml@refs/heads/main` y el TrustedRoot independiente. No se
modifican políticas externas al preparar esta PR.

La verificación posterior usa el mismo `verify-bootstrap.py --policy ...` y las
tres verificaciones tipadas existentes, sin omitir claims/tlog/SCT. El esquema 2
contrasta además provenance de promoción, candidato y commit del firmante;
conserva el builder/source/run originales. El esquema 1 mantiene su identidad
anterior. VERIFIED continúa indicando `deployment_authorized=false`.

Limitaciones operativas: el artifact original debe seguir disponible y no
caducado (retención original: siete días); si falta, se deniega, sin fallback a
rebuild u otra fuente. Skopeo debe existir en el runner; si falta, se aborta. La
copia real conservó el digest y generó SPDX en el run 41380381655. La publicación
de firma/atestaciones y la interoperabilidad criptográfica siguen pendientes;
las pruebas offline no acreditan esas operaciones.

### Autenticación compartida y recuperación pendiente

El fallo dejó un authfile accesible solo a Skopeo, sin configurar el keychain de
Cosign. El publicador usa ahora un directorio temporal `0700`, exportado como
`DOCKER_CONFIG`, con `config.json` `0600`. Skopeo recibe ese mismo archivo mediante
`--authfile`; los tres comandos Cosign heredan `DOCKER_CONFIG` en el mismo paso.
El token sigue entrando por stdin, sin argumentos de credenciales ni trazas;
el trap EXIT elimina el directorio, incluyendo fallos de login y de comandos
posteriores. INT/TERM provocan salida y la misma limpieza. El archivo permanece
fuera de las rutas de evidencia subidas. No cambian permisos de jobs o tokens.

Compatibilidad comprobada en fuente oficial, sin ejecutar Cosign: [Cosign
v3.1.4 RegistryOptions](https://github.com/sigstore/cosign/blob/v3.1.4/cmd/cosign/cli/options/registry.go)
selecciona `authn.DefaultKeychain`; su [dependencia go-containerregistry
v0.22.1](https://github.com/sigstore/cosign/blob/v3.1.4/go.mod) [carga
DOCKER_CONFIG/config.json](https://github.com/google/go-containerregistry/blob/v0.22.1/pkg/authn/keychain.go).
El formato `auths` escrito por Skopeo es compatible con ese Docker config.
Las pruebas usan datos ficticios y un stub de login, nunca herramientas de firma
ni credenciales reales; comprueban propagación, permisos y limpieza.

**Recuperación bloqueada en este workflow:** todavía ejecuta `skopeo copy` sin
condición. No usarlo para recuperar la imagen ya publicada: volvería a publicar
las capas. Una recuperación segura debe primero exigir el manifiesto existente
por su digest exacto, inventariar y verificar de forma autenticada las evidencias
tipadas ya publicadas, y generar únicamente las faltantes sin duplicar firmas o
atestaciones. Esos controles no existen aún; no se añade un modo que simplemente
omita el push y vuelva a firmar todo. No se eliminan evidencias existentes y el
resultado parcial continúa sin verificar ni autorizar despliegue.

Esta corrección cambia el commit del promotor. Después de revisión/integración,
el propietario deberá aprobar expresamente el nuevo `signer_commit` y la política
externa correspondiente antes de autorizar cualquier operación. La política
esquema 2 anterior permanece intacta y no autoriza el workflow modificado.
