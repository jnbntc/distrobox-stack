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
4. Syft 1.55.0 escanea registry:<imagen@digest> sin ejecutarla; genera SPDX 2.3. Cosign 3.1.4 firma y atesta el SBOM y la provenance custom sobre esa misma referencia.
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
1. verify, salida JSON, sobre imagen@digest.
2. verify-attestation --type spdxjson, sobre la misma imagen.
3. verify-attestation --type <URI de provenance anterior>, sobre la misma imagen.

Los tres comandos exigen --certificate-identity, --certificate-oidc-issuer, --certificate-github-workflow-repository, --certificate-github-workflow-ref, --certificate-github-workflow-sha y --certificate-github-workflow-trigger exactos; --trusted-root explícito, --check-claims=true, --insecure-ignore-tlog=false y --insecure-ignore-sct=false.
Cosign realiza la criptografía, validación de certificados/transparencia y asociación del digest. Se inspeccionaron opciones/salidas de v3.1.4 para preparar este adaptador; su interoperabilidad real sigue pendiente de prueba.

Solo tras un exit 0 de cada comando se interpreta su stdout:
- Firma: repositorio y digest exactos.
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
Se ejecutaron pruebas estáticas y fixtures con Cosign simulado: prueban errores/parámetros/parsers, no criptografía real.
Faltan build/publicación autorizados; verificar firmas/atestaciones reales y casos negativos reales de identidad/issuer/subject/source; comprobar compatibilidad GHCR/referrers/formato; probar mounts/SELinux y persistencia con Distrobox autorizado.
RPM móviles e inicialización no fijada siguen limitando rebuilds. Integridad, autenticidad, provenance, repetibilidad de consumo por digest y reproducibilidad de build son garantías distintas; ninguna es equivalente a que una receta exista.
Referencias: [Cosign verify](https://docs.sigstore.dev/cosign/verifying/verify/), [atestaciones](https://docs.sigstore.dev/cosign/verifying/attestation/), [Cosign v3.1.4](https://github.com/sigstore/cosign/tree/v3.1.4).
