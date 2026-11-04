# TF-003 native OCI promotion

GHCR recovery is abandoned. Existing GHCR artifacts and all historical policies
remain untouched. The new manual workflow is `trustforge-native-promote.yml`.
No workflow was dispatched, candidate republished, or real signature generated
while preparing this change.

## Actual local registry evidence

Zot **v2.1.23**, official image pinned as
`ghcr.io/project-zot/zot@sha256:9d3de83ac2099e6f4843045b4c9b65b7e8baf40f92d28f54906dee9d4d390fd7`,
was run rootless, read-only, ephemeral storage, no capabilities, and mapped only
to `127.0.0.1:18583`. No production credentials or real candidate were supplied.
`test-zot-live.py` exercises `/v2/`, an initialized synthetic repository with no
referrers (200 and empty OCI index), three untagged subject manifests, unfiltered
inventory, artifactType/subject/bytes, and Skopeo readback. `zot-probe-result.json`
records the local result. Zot returned all three in one page despite `n=1`;
**actual multi-page server behavior was not tested**. This does not establish
Cosign interoperability or remote TLS/authentication interoperability.

The production client rejects **any Link**, rather than accepting a partial
inventory: only three total evidence roles are approved. HTTP failures, unknown
formats, duplicate roles/descriptors, legacy tags, and invalid cryptography DENY.
The registry's enumeration itself is trusted operationally, not cryptographically
proven complete. Neither this test nor OCI compliance proves that an adversarial
registry cannot omit records. Repository freshness, exclusive writers, no delete/
retention/GC during promotion, and the exact tested deployment are owner-approved
preconditions, not properties inferred from a checksum or empty response.

## Before any real write

1. Owner selects/deploys a TLS Zot destination separately; this PR deploys nothing.
   Pin the deployment to the tested version/image, disable retention/GC during
   promotion, approve a fresh namespace and account with complete catalog/read
   access and exclusive writes. No other writers, sync/importers, or automatic
   evidence producers may target it. Repository catalog must be complete under
   that account; pagination or unexpected existing namespace blocks promotion.
2. After merge, independently prepare and approve **external** schema-4 policy:
   start from `native-policy.example.json`, set the exact destination, actual
   `signer_commit`, owner-generated `namespace_approval` identifier, and only then
   `approved=true`. Keep original source commit, issuer, authenticated root hash
   and identity fixed. Do not reuse GHCR schema 2/3 approvals. Hash canonical JSON
   using sorted keys, separators `(',', ':')`, UTF-8, no trailing newline. Confirm
   the exact `PROMOTE-NATIVE ... destination=... policy=sha256:...` string produced
   by `promote-native.py`'s `confirmation(policy)` function.
3. Separately authorize repository vars `TF_NATIVE_DESTINATION` and
   `TF_NATIVE_NAMESPACE_APPROVAL`, and environment-scoped secrets
   `TF_NATIVE_REGISTRY_USERNAME`/`TF_NATIVE_REGISTRY_PASSWORD` in the existing
   main-only `trustforge-bootstrap-publish` environment. Review its effective
   restrictions before dispatch. This preparation does not create any setting.
   The hash and full confirmation are dispatch inputs, never shell-interpolated
   expressions. The read-only validation job has no registry or OIDC credentials.

The signer job rechecks exact original run/attempt/artifact and complete ZIP/tar,
then checks fresh namespace before copy. Skopeo preserves digests and verifies the
remote manifest bytes. The strict native inventory must be empty **after** image
copy. Each subsequent Cosign write is preceded/followed by authenticated scans;
unknown, partial ambiguous or concurrent state aborts. There is no automatic retry,
replacement or recovery mode. On failure the destination remains unverified and
requires review; never reuse it as a fresh namespace.

Dedicated signature, SPDX and provenance all bind the original manifest digest.
Provenance retains original source, build parameters (including historical GHCR
repository) and materials, and adds the new destination, workflow, signer and run.
Cosign 3.1.4 keyless signs; verification pins exact identity, issuer, signer SHA,
workflow repository/ref/trigger, binary hash, TrustedRoot hash, claims, tlog and SCT.
The pinned root target is retrieved and hash-checked; its authentication is the
previously approved TUF evidence, not a new trust-on-first-use decision.

## Independent verification and expiry

From an independently trusted checkout/tool/root and read-only destination account:

```sh
python3 -B workspaces/trustforge-dev/promote-native.py verify \
  --policy /private/approved-native-policy.json \
  --cosign /absolute/trusted/cosign \
  --trusted-root /absolute/authenticated/trusted_root.json \
  --output /private/native-verification
```

Cosign/GitHub OIDC real interoperability, production TLS/credentials, and a
concrete destination remain **NOT VERIFIED**. `VERIFIED` never authorizes deployment.

The original Actions artifact expires **2026-11-08 20:02:47 UTC**. Its complete
local tar/ZIP/config/manifest/build record and historical origin evidence were
revalidated and preserved privately on 2026-11-04, with a hash inventory. The
workflow deliberately still requires the original unexpired artifact and fails
closed after expiry. A future transfer of preserved bytes with an explicitly
reviewed transport is required if dispatch is delayed beyond expiration; this PR
never silently substitutes a different artifact or trusts arbitrary download URLs.
The extra-disk backup was not performed because automatic approval rejected the
unapproved destination. Original files/policies are intact.

## Validation scope

`test-native-promotion.py` is offline: cryptographic outcomes are mocks, never
proof of signature interoperability. Existing strict discovery/recovery tests also
cover malformed/referrer duplicates/unknown predicates and partial state. The live
Zot probe uses synthetic unsigned artifacts only. No Cosign, Syft or candidate
execution occurs during tests. Existing builder/publisher/recovery workflows are
unchanged; dispatching them is not part of this migration.
