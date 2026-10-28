#!/usr/bin/env python3
"""Independent bootstrap verifier. Cryptography is delegated ONLY to pinned Cosign.
No engine, install, deploy, offline-JSON acceptance or trust-bypass mode exists.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPOSITORY = "ghcr.io/jnbntc/trustforge-dev"
WORKFLOW = "jnbntc/distrobox-stack/.github/workflows/trustforge-dev.yml@refs/heads/main"
IDENTITY = "https://github.com/" + WORKFLOW
ISSUER = "https://token.actions.githubusercontent.com"
PROVENANCE = "https://github.com/jnbntc/distrobox-stack/workspaces/trustforge-dev/provenance/v1"
SPDX = "https://spdx.dev/Document"
HEX = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")


class VerificationError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise VerificationError(reason)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decoder():
    def invalid_constant(value):
        raise VerificationError("non-finite JSON constant")
    return json.JSONDecoder(object_pairs_hook=no_duplicates, parse_constant=invalid_constant)


def strict_json(raw):
    try:
        return decoder().decode(raw)
    except (ValueError, TypeError) as error:
        raise VerificationError("invalid JSON") from error


def image_digest(image):
    prefix = REPOSITORY + "@sha256:"
    require(isinstance(image, str) and image.startswith(prefix), "unexpected image repository or mutable tag")
    digest = image[len(prefix):]
    require(HEX.fullmatch(digest) is not None, "invalid OCI digest")
    return digest


def check_policy(policy):
    require(isinstance(policy, dict), "policy must be an object")
    expected = {"schema_version", "approved", "issuer", "identity", "repository",
                "workflow_ref", "trigger", "source_commit", "trusted_root_sha256"}
    require(set(policy) == expected, "unexpected policy keys")
    require(policy["schema_version"] == 1 and type(policy["schema_version"]) is int, "invalid policy version")
    require(policy["approved"] is True, "trust policy requires explicit human approval")
    require(policy["issuer"] == ISSUER, "unexpected issuer")
    require(policy["identity"] == IDENTITY, "unexpected signer workflow identity")
    require(policy["repository"] == "jnbntc/distrobox-stack", "unexpected source repository")
    require(policy["workflow_ref"] == "refs/heads/main", "unexpected source ref")
    require(policy["trigger"] == "workflow_dispatch", "unexpected workflow trigger")
    require(isinstance(policy["source_commit"], str) and COMMIT.fullmatch(policy["source_commit"]), "source commit not approved")
    require(isinstance(policy["trusted_root_sha256"], str) and HEX.fullmatch(policy["trusted_root_sha256"]), "trusted root not approved")


def verified_documents(raw):
    # Cosign 3.1.4 verify-attestation emits one verified DSSE envelope per line.
    # Accept a JSON array too, but reject bare unverified in-toto statements.
    result = []
    remaining = raw.strip()
    parser = decoder()
    try:
        while remaining:
            value, end = parser.raw_decode(remaining)
            result.extend(value if isinstance(value, list) else [value])
            remaining = remaining[end:].lstrip()
    except (ValueError, TypeError) as error:
        raise VerificationError("malformed Cosign output") from error
    require(bool(result), "missing verified evidence")
    require(all(isinstance(item, dict) for item in result), "unexpected Cosign output")
    return result


def signature_claims(raw, image):
    image_digest(image)
    for signature in verified_documents(raw):
        critical = signature.get("critical", {})
        require(isinstance(critical, dict), "malformed signature claims")
        identity = critical.get("identity", {})
        artifact = critical.get("image", {})
        require(isinstance(identity, dict) and isinstance(artifact, dict), "malformed signature claims")
        require(identity.get("docker-reference") in (REPOSITORY, image), "signature repository mismatch")
        require(artifact.get("docker-manifest-digest") == "sha256:" + image_digest(image), "signature digest mismatch")


def statements(raw, image, predicate_type):
    digest = image_digest(image)
    result = []
    for envelope in verified_documents(raw):
        require(envelope.get("payloadType") == "application/vnd.in-toto+json", "unexpected DSSE payload type")
        require(isinstance(envelope.get("payload"), str), "missing DSSE payload")
        try:
            decoded = base64.b64decode(envelope["payload"], validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as error:
            raise VerificationError("invalid DSSE encoding") from error
        statement = strict_json(decoded)
        require(isinstance(statement, dict), "malformed statement")
        require(statement.get("_type") in ("https://in-toto.io/Statement/v0.1", "https://in-toto.io/Statement/v1"), "unexpected in-toto type")
        require(statement.get("predicateType") == predicate_type, "unexpected predicate type")
        subjects = statement.get("subject")
        require(isinstance(subjects, list) and len(subjects) == 1, "ambiguous or missing subject")
        subject = subjects[0]
        require(isinstance(subject, dict) and subject.get("name") in (REPOSITORY, image), "subject repository mismatch")
        require(subject.get("digest") == {"sha256": digest}, "subject digest mismatch")
        require(isinstance(statement.get("predicate"), dict), "missing predicate")
        result.append(statement["predicate"])
    return result


def expected_materials(contract):
    return {
        "base_image": contract["base"]["reference"] + "@" + contract["base"]["manifest_digest"],
        "uv_image": contract["uv"]["reference"] + "@" + contract["uv"]["manifest_digest"],
        "python_archive_sha256": contract["python"]["sha256"],
        "tool_lock_sha256": contract["requirements"]["sha256"],
    }


def check_predicates(sboms, provenances, policy, contract, image):
    require(bool(sboms) and bool(provenances), "missing SBOM or provenance")
    for sbom in sboms:
        require(sbom.get("spdxVersion") == "SPDX-2.3", "unexpected SBOM version")
        require(sbom.get("SPDXID") == "SPDXRef-DOCUMENT", "invalid SBOM document")
        require(isinstance(sbom.get("documentNamespace"), str) and bool(sbom["documentNamespace"]), "missing SBOM namespace")
        packages = sbom.get("packages")
        require(isinstance(packages, list) and len(packages) > 0, "empty SBOM")
        require(all(isinstance(p, dict) and isinstance(p.get("name"), str) and bool(p["name"]) for p in packages), "malformed SBOM packages")
    for provenance in provenances:
        require(provenance.get("artifact") == image, "provenance artifact mismatch")
        require(provenance.get("schema_version") == 1 and type(provenance.get("schema_version")) is int, "unexpected provenance schema")
        require(provenance.get("source") == {
            "repository": "https://github.com/jnbntc/distrobox-stack",
            "commit": policy["source_commit"], "ref": "refs/heads/main",
        }, "source revision/repository mismatch")
        require(provenance.get("builder") == {
            "id": IDENTITY, "workflow_ref": WORKFLOW,
            "workflow_sha": policy["source_commit"],
            "event": "workflow_dispatch",
        }, "builder/workflow mismatch")
        require(provenance.get("parameters") == {
            "platform": contract["platform"],
            "containerfile": "workspaces/trustforge-dev/Containerfile",
            "image_repository": REPOSITORY,
        }, "unexpected build parameters")
        require(provenance.get("materials") == expected_materials(contract), "build material mismatch")
        run = provenance.get("invocation", {})
        require(isinstance(run, dict) and re.fullmatch(r"[1-9][0-9]*", str(run.get("run_id", ""))), "missing build run")
        require(re.fullmatch(r"[1-9][0-9]*", str(run.get("attempt", ""))), "missing build attempt")


def cosign_commands(binary, root, policy, image):
    image_digest(image)
    check_policy(policy)
    common = [
        "--certificate-identity", policy["identity"],
        "--certificate-oidc-issuer", policy["issuer"],
        "--certificate-github-workflow-repository", policy["repository"],
        "--certificate-github-workflow-ref", policy["workflow_ref"],
        "--certificate-github-workflow-sha", policy["source_commit"],
        "--certificate-github-workflow-trigger", policy["trigger"],
        "--trusted-root", str(root), "--check-claims=true",
        "--insecure-ignore-tlog=false", "--insecure-ignore-sct=false",
    ]
    return [
        [str(binary), "verify", *common, "--output", "json", image],
        [str(binary), "verify-attestation", *common, "--type", "spdxjson", image],
        [str(binary), "verify-attestation", *common, "--type", PROVENANCE, image],
    ]


def invoke(command):
    # A caller's COSIGN/SIGSTORE configuration must not select different roots.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("COSIGN_", "SIGSTORE_", "FULCIO_", "REKOR_"))}
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True,
                                timeout=180, env=env)
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise VerificationError("Cosign verification failed; no fallback") from error
    return result.stdout


def verify(image, policy, contract, binary, root):
    check_policy(policy)
    image_digest(image)
    require(binary.is_absolute() and binary.is_file(), "explicit trusted Cosign binary required")
    require(root.is_absolute() and root.is_file(), "explicit trusted-root file required")
    require(hashlib.sha256(binary.read_bytes()).hexdigest() == contract["bootstrap"]["cosign"]["sha256"], "Cosign binary hash mismatch")
    root_bytes = root.read_bytes()
    require(hashlib.sha256(root_bytes).hexdigest() == policy["trusted_root_sha256"], "trusted-root hash mismatch")
    # Use the same reviewed root bytes for all checks, even if an operator updates
    # the original file while remote verification is in progress.
    with tempfile.TemporaryDirectory(prefix="trustforge-bootstrap-") as temp:
        checked_root = Path(temp) / "trusted-root.json"
        checked_root.write_bytes(root_bytes)
        commands = cosign_commands(binary, checked_root, policy, image)
        # Only stdout from successful cryptographic verification reaches parsers.
        signature_claims(invoke(commands[0]), image)
        sboms = statements(invoke(commands[1]), image, SPDX)
        provenances = statements(invoke(commands[2]), image, PROVENANCE)
    check_predicates(sboms, provenances, policy, contract, image)
    return {
        "verification": "VERIFIED",
        "image": image, "source_commit": policy["source_commit"],
        "identity": policy["identity"], "issuer": policy["issuer"],
        "trusted_root_sha256": policy["trusted_root_sha256"],
        "cosign_version": contract["bootstrap"]["cosign"]["version"],
        "sbom_predicate": SPDX, "provenance_predicate": PROVENANCE,
        "deployment_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--policy", required=True, type=Path, help="Locally reviewed approval policy, never from image artifacts")
    parser.add_argument("--cosign", required=True, type=Path, help="Absolute path to independently trusted Cosign")
    parser.add_argument("--trusted-root", required=True, type=Path, help="Absolute path to reviewed Sigstore TrustedRoot JSON")
    args = parser.parse_args()
    try:
        policy_bytes = args.policy.read_bytes()
        policy = strict_json(policy_bytes.decode("utf-8"))
        contract = strict_json((HERE / "contract.json").read_text())
        result = verify(args.image, policy, contract, args.cosign, args.trusted_root)
        result["policy_sha256"] = hashlib.sha256(policy_bytes).hexdigest()
        print(json.dumps(result, sort_keys=True))
    except (VerificationError, OSError, TypeError, KeyError, UnicodeError) as error:
        print(json.dumps({"verification": "DENY", "reason": str(error), "deployment_authorized": False}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
