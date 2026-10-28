# Firma dedicada — interfaz de Cosign 3.1.4

Estado: semántica contrastada con fuente oficial; tests con mocks/fixtures. **Sin Cosign real ni interoperabilidad criptográfica con GHCR probada.**

## Causa raíz
El adaptador anterior aceptaba como firma una salida genérica critical.* si coincidían repositorio y digest, sin comprobar el tipo.
En bundles v3, cosign verify usa VerifyImageAttestations y transformOutput proyecta distintos statements en esa estructura. La fixture positiva anterior también omitía el tipo.
Sobre el head 2998e59790416c491d65fced798554a97c3e3b02, tres casos offline sin firma dedicada devolvieron VERIFIED: proyección SBOM, provenance y ambas. Con las mismas respuestas simuladas, la corrección devuelve DENY al primer paso. Es un defecto del adaptador, no una ruptura criptográfica demostrada de Cosign.

## Contrato tomado de fuente oficial
Tag v3.1.4 resuelto al commit `0e48502cf5ef34e2e60bbd3617aa19945712f705`.

| Fuente | Semántica utilizada |
|---|---|
| [predicate.go:19](https://github.com/sigstore/cosign/blob/0e48502cf5ef34e2e60bbd3617aa19945712f705/pkg/types/predicate.go#L19) | Firma dedicada: https://sigstore.dev/cosign/sign/v1 |
| [signDigestBundle](https://github.com/sigstore/cosign/blob/0e48502cf5ef34e2e60bbd3617aa19945712f705/cmd/cosign/cli/sign/sign.go#L158) | sign en formato nuevo genera in-toto v1, digest/annotations en subject, predicate vacío y no fija subject.name |
| [SignOptions](https://github.com/sigstore/cosign/blob/0e48502cf5ef34e2e60bbd3617aa19945712f705/cmd/cosign/cli/options/sign.go#L161) | new-bundle-format es una opción real, true por defecto |
| [AnnotationOptions](https://github.com/sigstore/cosign/blob/0e48502cf5ef34e2e60bbd3617aa19945712f705/cmd/cosign/cli/options/annotations.go#L50) | -a/--annotations incorpora key=value firmados |
| [transformOutput](https://github.com/sigstore/cosign/blob/0e48502cf5ef34e2e60bbd3617aa19945712f705/cmd/cosign/cli/verify/verify.go#L273) | Proyecta predicateType en critical.type; no constituye por sí solo una firma dedicada |
| [AttestationToPayloadJSON](https://github.com/sigstore/cosign/blob/0e48502cf5ef34e2e60bbd3617aa19945712f705/pkg/policy/attestation.go#L98) | Filtra el predicateType exacto, también cuando el selector es una URI |
| [verify-attestation](https://github.com/sigstore/cosign/blob/0e48502cf5ef34e2e60bbd3617aa19945712f705/cmd/cosign/cli/verify/verify_attestation.go#L272) | Falla sin coincidencias y emite envelopes DSSE verificados en modo text |

Las fixtures modelan esas estructuras: no son capturas ni certificados/firmas reales.

## Tres roles obligatorios y separados
| Rol | Selector nativo verify-attestation --type | Validación posterior a exit 0 |
|---|---|---|
| Firma de imagen dedicada | https://sigstore.dev/cosign/sign/v1 | DSSE/in-toto v1; predicate vacío; un subject del digest exacto; anotación firmada de repositorio |
| SBOM | spdxjson, mapeado a https://spdx.dev/Document | Subject nombrado del repositorio/digest; SPDX no vacío |
| Provenance | URI custom canónica de contract.json | Subject nombrado; artefacto/origen/builder/parámetros/materiales aprobados |

Cada invocación conserva identidad/issuer exactos, workflow repository/ref/trigger/source SHA, TrustedRoot explícito y hashes de herramienta/raíces, claims/tlog/SCT y aprobación de política.
No se acepta una evidencia en sustitución de otra. El formato admitido es el text nativo de esta versión: objetos JSON DSSE separados por whitespace. Arrays/proyecciones genéricas, tipos erróneos, salidas vacías, duplicados de envelope o statement, JSON/encoding malformado se deniegan; sin fallback legacy.

## Binding firmado de repositorio
signDigestBundle no fija subject.name. No se inventa ese nombre ni se usa el sintetizado por transformOutput como si estuviera firmado.
La futura invocación preparada es:
```bash
cosign sign --yes --new-bundle-format=true \
  -a io.trustforge.repository=ghcr.io/jnbntc/trustforge-dev "$image"
```
El verificador exige la anotación dentro del subject firmado, además de tipo y digest. Si name aparece, también debe ser coherente. Sin anotación se deniega; no se creó ni volvió a firmar ningún artefacto real.
Este requisito usa la extensión de anotaciones soportada por Cosign; no prueba qué comando ejecutó históricamente el firmante. Clasifica el statement autenticado bajo la identidad/workflow/source aprobados. Un builder/firmante autorizado comprometido sigue siendo un riesgo.

## Tests y pruebas pendientes
Se cubren solo SBOM/provenance, proyección genérica como firma, atestación relabelada con predicate no vacío, digest/repositorio/anotación incorrectos, identidad rechazada por Cosign simulado, firma ausente/vacía, duplicados/malformación y fallo en cualquiera de las tres verificaciones.
La política entregada sigue sin aprobar y VERIFIED mantiene deployment_authorized=false.
Faltan artefactos reales autorizados para probar selectores/formato/referrers, anotación, certificados/tlog/SCT e interoperabilidad Cosign 3.1.4/GHCR, incluyendo negativos criptográficos reales. No hay afirmación de seguridad criptográfica basada en los mocks.
La política conservadora también deniega statements idénticos publicados legítimamente más de una vez. Revisar ese caso con evidencias reales antes de considerar compatibilidad de reintentos; no se deduplican ni se limpian firmas automáticamente.
