#!/usr/bin/env python3
"""Targeted offline lint, schema and negative tests for trustforge-dev only.
Fixture success is NOT a real Cosign/Sigstore verification or a container test.
"""
import ast
import base64
import configparser
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renderer = load_module("manifest_renderer", "render-manifest.py")
bootstrap = load_module("bootstrap_verifier", "verify-bootstrap.py")
maker = load_module("provenance_maker", "make-provenance.py")
CONTRACT = bootstrap.strict_json((HERE / "contract.json").read_text())
IMAGE = CONTRACT["output"]["repository"] + "@sha256:" + "a" * 64
POLICY = bootstrap.strict_json((HERE / "trust-policy.example.json").read_text())
MANUAL = ROOT / ".github/workflows/trustforge-dev.yml"
STATIC = ROOT / ".github/workflows/trustforge-static.yml"


def lint_containerfile(text, contract):
    instructions = []
    run_count = 0
    for line in text.replace("\\\n", " ").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        opcode = line.split()[0]
        assert opcode in {"FROM", "LABEL", "COPY", "RUN", "ENV", "WORKDIR", "CMD"}, opcode
        instructions.append((opcode, line))
        if opcode == "FROM":
            assert re.fullmatch(r"FROM \S+@sha256:[0-9a-f]{64}(?: AS [a-z]+)?", line), line
        if opcode == "RUN":
            subprocess.run(["bash", "-n"], input=line[4:], text=True, check=True)
            assert not re.search(r"curl[^|]*\|\s*(sh|bash)", line)
            run_count += 1
        if opcode == "COPY" and "--from=uv" not in line:
            parts = line.split()
            assert len(parts) == 3
            source = parts[1]
            assert source in {"workspaces/trustforge-dev/requirements.lock", "workspaces/trustforge-dev/contract.json"}
            assert (ROOT / source).is_file()
        if opcode == "CMD":
            assert json.loads(line[4:]) == ["/bin/bash"]
    assert run_count == 2
    assert sum(op == "FROM" for op, _ in instructions) == 2
    for key in ("base", "uv"):
        assert "FROM " + contract[key]["reference"] + "@" + contract[key]["manifest_digest"] in text
    for forbidden in ("podman.sock", "docker.sock", "--privileged", "--security=insecure"):
        assert forbidden not in text


def lint_workflows(manual, static):
    # Files are JSON documents, a strict YAML 1.2 subset understood by Actions.
    # Stdlib parsing gives full structural checks without installing a YAML tool.
    assert set(manual["on"]) == {"workflow_dispatch"}
    publish_input = manual["on"]["workflow_dispatch"]["inputs"]["publish"]
    assert publish_input["type"] == "boolean" and publish_input["default"] is False
    assert manual["permissions"] == {"contents": "read"}
    assert set(manual["jobs"]) == {"build", "publish"}
    build, publish = manual["jobs"]["build"], manual["jobs"]["publish"]
    assert build["if"] == "github.ref == 'refs/heads/main'"
    assert publish["if"] == "github.ref == 'refs/heads/main' && inputs.publish == true"
    assert build["permissions"] == {"contents": "read"}
    assert publish["permissions"] == {"contents": "read", "packages": "write", "id-token": "write"}
    assert publish["needs"] == "build"
    assert publish["environment"] == "trustforge-bootstrap-publish"
    assert set(static["on"]) == {"pull_request", "workflow_dispatch"}
    assert static["on"]["pull_request"]["branches"] == ["main"]
    assert set(static["on"]["pull_request"]["paths"]) == {
        "workspaces/trustforge-dev/**", ".github/workflows/trustforge-dev.yml",
        ".github/workflows/trustforge-static.yml",
    }
    assert static["permissions"] == {"contents": "read"}
    assert set(static["jobs"]) == {"static"}
    assert static["jobs"]["static"]["permissions"] == {"contents": "read"}
    static_steps = static["jobs"]["static"]["steps"]
    assert len(static_steps) == 2
    assert static_steps[1]["run"] == "python3 -B workspaces/trustforge-dev/validate-static.py"
    for workflow in (manual, static):
        for job in workflow["jobs"].values():
            assert "strategy" not in job  # Never widen into the existing image matrix.
            for step in job["steps"]:
                if "uses" in step:
                    assert re.fullmatch(r"(actions|sigstore|anchore)/[a-zA-Z0-9_/-]+@[0-9a-f]{40}", step["uses"])
                    if step["uses"].startswith("actions/checkout@"):
                        assert step["with"] == {"persist-credentials": False}
                if "run" in step:
                    subprocess.run(["bash", "-n"], input=step["run"], text=True, check=True)
    uses = {s.get("uses"): s for s in publish["steps"] if "uses" in s}
    cosign = CONTRACT["bootstrap"]["cosign"]
    syft = CONTRACT["bootstrap"]["syft"]
    assert uses[cosign["installer_action"]]["with"]["cosign-release"] == cosign["version"]
    assert uses[syft["action"]]["with"]["syft-version"] == syft["version"]
    run = "\n".join(s.get("run", "") for s in publish["steps"])
    assert cosign["sha256"] in run
    assert "-a io.trustforge.repository=ghcr.io/jnbntc/trustforge-dev" in run
    assert CONTRACT["bootstrap"]["image_signature"]["predicate_type"] == bootstrap.IMAGE_SIGNATURE
    assert CONTRACT["bootstrap"]["image_signature"]["repository_annotation"] == bootstrap.REPOSITORY_ANNOTATION
    assert CONTRACT["bootstrap"]["image_signature"]["legacy_projection_accepted"] is False
    for required in ('syft scan "registry:$image"', 'cosign sign --yes --new-bundle-format=true',
                     "--type spdxjson", bootstrap.PROVENANCE):
        assert required in run
    assert "stack.sh" not in run and ":latest" not in run
    assert "podman run" not in run and "distrobox" not in run.replace("distrobox-stack", "")
    build_run = "\n".join(s.get("run", "") for s in build["steps"])
    assert "workspaces/trustforge-dev/Containerfile" in build_run
    assert "podman build --platform linux/amd64" in build_run
    assert build_run.index("podman build") < build_run.index("--record-build")
    assert run.index("--record-build") < run.index("podman push")


def fixture_policy():
    result = copy.deepcopy(POLICY)
    result.update(approved=True, source_commit="b" * 40, trusted_root_sha256="c" * 64)
    return result


def fixture_sbom():
    return {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT",
            "documentNamespace": "https://fixture.invalid/sbom",
            "packages": [{"name": "fixture-only"}]}


def fixture_provenance():
    p = fixture_policy()
    return {
        "schema_version": 1, "artifact": IMAGE,
        "source": {"repository": "https://github.com/jnbntc/distrobox-stack", "commit": p["source_commit"], "ref": "refs/heads/main"},
        "builder": {"id": bootstrap.IDENTITY, "workflow_ref": bootstrap.WORKFLOW,
                    "workflow_sha": p["source_commit"], "event": "workflow_dispatch"},
        "parameters": {"platform": CONTRACT["platform"], "containerfile": "workspaces/trustforge-dev/Containerfile", "image_repository": bootstrap.REPOSITORY},
        "materials": bootstrap.expected_materials(CONTRACT),
        "invocation": {"run_id": "123", "attempt": "1"},
    }


def fixture_envelope(predicate, kind):
    # Deliberately NOT signed. Only for parsers after mocked successful Cosign.
    statement = {"_type": "https://in-toto.io/Statement/v1", "predicateType": kind,
                 "subject": [{"name": bootstrap.REPOSITORY, "digest": {"sha256": "a" * 64}}],
                 "predicate": predicate}
    return {"payloadType": "application/vnd.in-toto+json",
            "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
            "signatures": []}


def fixture_signature_statement(digest="a" * 64, repository=bootstrap.REPOSITORY):
    # Source-based shape: Cosign 3.1.4 sign.signDigestBundle, nameless subject.
    return {"_type": "https://in-toto.io/Statement/v1",
            "subject": [{"digest": {"sha256": digest},
                         "annotations": {bootstrap.REPOSITORY_ANNOTATION: repository}}],
            "predicateType": bootstrap.IMAGE_SIGNATURE, "predicate": {}}


def fixture_signature(digest="a" * 64, repository=bootstrap.REPOSITORY):
    statement = fixture_signature_statement(digest, repository)
    return json.dumps({"payloadType": "application/vnd.in-toto+json",
                       "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
                       "signatures": []})  # Mocked verified stdout, NOT a signature.


@contextlib.contextmanager
def fixture_verification_inputs():
    with tempfile.TemporaryDirectory() as tmp:
        binary, root = Path(tmp) / "cosign", Path(tmp) / "root.json"
        binary.write_bytes(b"fixture, not executable")
        root.write_text('{"fixture":true}')
        policy = fixture_policy()
        policy["trusted_root_sha256"] = hashlib.sha256(root.read_bytes()).hexdigest()
        contract = copy.deepcopy(CONTRACT)
        contract["bootstrap"]["cosign"]["sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        yield policy, contract, binary, root


def fixture_responses():
    return [fixture_signature(),
            json.dumps(fixture_envelope(fixture_sbom(), bootstrap.SPDX)),
            json.dumps(fixture_envelope(fixture_provenance(), bootstrap.PROVENANCE))]


def fixture_generic_projection(kinds):
    # Mirrors v3.1.4 verify.transformOutput's fields; no real crypto executed.
    return json.dumps([{"critical": {
        "identity": {"docker-reference": IMAGE},
        "image": {"docker-manifest-digest": "sha256:" + "a" * 64},
        "type": kind}, "optional": {}} for kind in kinds])


class WorkspaceContract(unittest.TestCase):
    def test_source_contract_lint_and_syntax(self):
        lint_containerfile((HERE / "Containerfile").read_text(), CONTRACT)
        self.assertEqual(CONTRACT["schema_version"], 1)
        self.assertEqual(CONTRACT["platform"], "linux/amd64")
        self.assertEqual(CONTRACT["security_model"]["scope"], "trusted-development-only")
        self.assertFalse(CONTRACT["security_model"]["adversarial_sandbox"])
        self.assertIn("uv python install " + CONTRACT["python"]["selector"], (HERE / "Containerfile").read_text())
        for p in HERE.glob("*.py"):
            ast.parse(p.read_text(), filename=str(p))

    def test_hashed_tool_lock_all_lines(self):
        raw = (HERE / CONTRACT["requirements"]["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CONTRACT["requirements"]["sha256"])
        entries = re.split(r"\n(?=[a-zA-Z0-9_.-]+==)", raw.decode().strip())
        self.assertEqual(len(entries), 11)
        names = []
        for entry in entries:
            lines = entry.splitlines()
            self.assertRegex(lines[0], r"^[a-zA-Z0-9_.-]+==[0-9][^\s;]* \\$")
            names.append(lines[0].split("==")[0])
            for line in lines[1:]:
                self.assertRegex(line, r"^    --hash=sha256:[0-9a-f]{64}(?: \\)?$")
        self.assertEqual(len(names), len(set(names)))
        for name, version in CONTRACT["tools"].items():
            self.assertRegex(raw.decode(), rf"(?m)^{re.escape(name)}=={re.escape(version)}(?:\s|$)")
        for line in (HERE / "requirements.in").read_text().splitlines():
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^(pytest|ruff|mypy)>=[0-9.]+,<[0-9.]+$")

    def test_manifest_only_new_rootless_workspace(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(renderer.render(IMAGE, "/tmp/fixture-home"))
        self.assertEqual(config.sections(), ["trustforge-dev"])
        entry = config["trustforge-dev"]
        self.assertEqual(entry["image"], IMAGE)
        for key in ("root", "replace", "pull", "start_now", "entry", "init", "nvidia"):
            self.assertEqual(entry[key], "false")
        self.assertEqual(entry["unshare_all"], "true")
        self.assertEqual(entry["volume"], '"/tmp/fixture-home/Proyectos/trustforge:/workspace/trustforge:rw"')
        for forbidden in ("--privileged", "--cap-add", "--device", "label=disable", ".sock", ":z", ":Z"):
            self.assertNotIn(forbidden, entry["additional_flags"])

    def test_reject_manifest_tags_other_repos_and_path_injection(self):
        for image in ("ghcr.io/jnbntc/trustforge-dev:latest", "other@sha256:" + "a" * 64, IMAGE + "\nroot=true"):
            with self.subTest(image=image), self.assertRaises(ValueError):
                renderer.render(image, "/tmp/fixture-home")
        for home in ("/", "/tmp/../root", "/tmp/a b", "/tmp/a:b", "/tmp/$(id)", "/tmp/a\nroot=true", "relative"):
            with self.subTest(home=home), self.assertRaises(ValueError):
                renderer.render(IMAGE, home)

    def test_excluded_from_mass_operations_and_no_fabricated_outputs(self):
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read(ROOT / "distrobox.ini")
        self.assertNotIn("trustforge-dev", config.sections())
        self.assertNotIn('"trustforge-dev"', (ROOT / "scripts/stack.sh").read_text())
        for key in ("digest", "sbom", "signature", "provenance"):
            self.assertIsNone(CONTRACT["output"][key])
        self.assertFalse(CONTRACT["deployment"]["approved"])
        self.assertFalse(POLICY["approved"])
        self.assertIsNone(POLICY["source_commit"])
        self.assertIsNone(POLICY["trusted_root_sha256"])

    def test_workflow_routes_permissions_and_evidence_commands(self):
        lint_workflows(bootstrap.strict_json(MANUAL.read_text()), bootstrap.strict_json(STATIC.read_text()))

    def test_reject_unpinned_container_base(self):
        text = (HERE / "Containerfile").read_text()
        text = text.replace(CONTRACT["base"]["manifest_digest"], "latest")
        with self.assertRaises(AssertionError):
            lint_containerfile(text, CONTRACT)

    def test_reject_publication_on_pull_request_or_widened_permissions(self):
        for mutate in ("event", "permission", "guard", "matrix", "static-command"):
            manual = bootstrap.strict_json(MANUAL.read_text())
            static = bootstrap.strict_json(STATIC.read_text())
            if mutate == "event": manual["on"]["pull_request"] = {}
            if mutate == "permission": static["jobs"]["static"]["permissions"]["id-token"] = "write"
            if mutate == "guard": manual["jobs"]["publish"]["if"] = "true"
            if mutate == "matrix": manual["jobs"]["build"]["strategy"] = {"matrix": {"image": ["iot-dev"]}}
            if mutate == "static-command": static["jobs"]["static"]["steps"][1]["run"] = "podman build ."
            with self.subTest(mutate=mutate), self.assertRaises(AssertionError):
                lint_workflows(manual, static)


class BootstrapVerification(unittest.TestCase):
    def test_delivered_policy_denies_at_cli_without_cosign_or_network(self):
        result = subprocess.run([sys.executable, "-B", str(HERE / "verify-bootstrap.py"),
                                 "--image", IMAGE, "--policy", str(HERE / "trust-policy.example.json"),
                                 "--cosign", "/not-used/cosign", "--trusted-root", "/not-used/root.json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        response = json.loads(result.stderr)
        self.assertEqual(response["verification"], "DENY")
        self.assertIn("human approval", response["reason"])

    def test_unapproved_incomplete_or_changed_identity_policy_denied(self):
        with self.assertRaises(bootstrap.VerificationError):
            bootstrap.check_policy(POLICY)
        for field, value in (("approved", "true"), ("issuer", "https://wrong.invalid"),
                             ("identity", bootstrap.IDENTITY + ".*"), ("repository", "other/repo"),
                             ("workflow_ref", "refs/heads/feature"), ("trigger", "pull_request"),
                             ("source_commit", None), ("trusted_root_sha256", None)):
            p = fixture_policy()
            p[field] = value
            with self.subTest(field=field), self.assertRaises(bootstrap.VerificationError):
                bootstrap.check_policy(p)

    def test_commands_bind_all_crypto_checks_and_no_bypass(self):
        cmds = bootstrap.cosign_commands("/trusted/cosign", "/trusted/root.json", fixture_policy(), IMAGE)
        self.assertEqual([cmd[1] for cmd in cmds], ["verify-attestation"] * 3)
        self.assertEqual([cmd[cmd.index("--type") + 1] for cmd in cmds],
                         [bootstrap.IMAGE_SIGNATURE, "spdxjson", bootstrap.PROVENANCE])
        for cmd in cmds:
            self.assertEqual(cmd[-1], IMAGE)
            for flag in ("--certificate-identity", "--certificate-oidc-issuer", "--certificate-github-workflow-sha", "--trusted-root"):
                self.assertIn(flag, cmd)
            self.assertIn("--check-claims=true", cmd)
            self.assertIn("--insecure-ignore-tlog=false", cmd)
            self.assertIn("--insecure-ignore-sct=false", cmd)
            self.assertNotIn("--certificate-identity-regexp", cmd)
            self.assertNotIn("--key", cmd)

    def test_signature_digest_or_repository_mismatch_denied(self):
        bootstrap.signature_claims(fixture_signature(), IMAGE)
        for raw in (fixture_signature(digest="d" * 64),
                    fixture_signature(repository="ghcr.io/other/image"), "[]"):
            with self.assertRaises(bootstrap.VerificationError):
                bootstrap.signature_claims(raw, IMAGE)

    def test_dsse_subject_type_encoding_and_bare_json_denied(self):
        envelope = fixture_envelope(fixture_sbom(), bootstrap.SPDX)
        self.assertEqual(len(bootstrap.statements(json.dumps(envelope), IMAGE, bootstrap.SPDX)), 1)
        for mode in ("digest", "repo", "type", "base64", "bare", "empty", "many-subjects"):
            altered = copy.deepcopy(envelope)
            statement = json.loads(base64.b64decode(altered["payload"]))
            if mode == "digest": statement["subject"][0]["digest"]["sha256"] = "d" * 64
            if mode == "repo": statement["subject"][0]["name"] = "other"
            if mode == "type": statement["predicateType"] = bootstrap.PROVENANCE
            if mode == "many-subjects": statement["subject"].append(copy.deepcopy(statement["subject"][0]))
            altered["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
            if mode == "base64": altered["payload"] = "!bad!"
            raw = json.dumps(statement if mode == "bare" else altered)
            if mode == "empty": raw = ""
            with self.subTest(mode=mode), self.assertRaises(bootstrap.VerificationError):
                bootstrap.statements(raw, IMAGE, bootstrap.SPDX)

    def test_provenance_source_builder_materials_and_parameters_denied(self):
        bootstrap.check_predicates([fixture_sbom()], [fixture_provenance()], fixture_policy(), CONTRACT, IMAGE)
        for field in ("source", "builder", "materials", "parameters", "invocation", "artifact"):
            p = fixture_provenance()
            p[field] = {} if field != "artifact" else "wrong"
            with self.subTest(field=field), self.assertRaises(bootstrap.VerificationError):
                bootstrap.check_predicates([fixture_sbom()], [p], fixture_policy(), CONTRACT, IMAGE)

    def test_missing_or_empty_sbom_or_provenance_denied(self):
        for sboms, provs in (([], [fixture_provenance()]), ([fixture_sbom()], []),
                             ([dict(fixture_sbom(), packages=[])], [fixture_provenance()])):
            with self.assertRaises(bootstrap.VerificationError):
                bootstrap.check_predicates(sboms, provs, fixture_policy(), CONTRACT, IMAGE)

    def test_invalid_ambiguous_json_denied(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', "not-json"):
            with self.assertRaises(bootstrap.VerificationError):
                bootstrap.strict_json(raw)

    def test_cosign_failure_timeout_and_missing_executable_denied(self):
        for error in (subprocess.CalledProcessError(1, "cosign"), subprocess.TimeoutExpired("cosign", 180), OSError("absent")):
            with self.subTest(error=type(error).__name__), mock.patch.object(bootstrap.subprocess, "run", side_effect=error):
                with self.assertRaises(bootstrap.VerificationError):
                    bootstrap.invoke(["/trusted/cosign", "verify"])

    def test_mocked_pipeline_does_not_grant_deployment_and_hash_mismatch_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary, root = Path(tmp) / "cosign", Path(tmp) / "root.json"
            binary.write_bytes(b"fixture, not executable")
            root.write_text('{"fixture":true}')
            p = fixture_policy()
            p["trusted_root_sha256"] = hashlib.sha256(root.read_bytes()).hexdigest()
            contract = copy.deepcopy(CONTRACT)
            contract["bootstrap"]["cosign"]["sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
            outputs = [fixture_signature(), json.dumps(fixture_envelope(fixture_sbom(), bootstrap.SPDX)),
                       json.dumps(fixture_envelope(fixture_provenance(), bootstrap.PROVENANCE))]
            with mock.patch.object(bootstrap, "invoke", side_effect=outputs) as mocked:
                result = bootstrap.verify(IMAGE, p, contract, binary, root)
                self.assertEqual(mocked.call_count, 3)
                self.assertFalse(result["deployment_authorized"])
            for broken in ("tool", "root"):
                changed = copy.deepcopy(contract)
                policy = copy.deepcopy(p)
                if broken == "tool": changed["bootstrap"]["cosign"]["sha256"] = "0" * 64
                if broken == "root": policy["trusted_root_sha256"] = "0" * 64
                with mock.patch.object(bootstrap, "invoke") as mocked:
                    with self.assertRaises(bootstrap.VerificationError):
                        bootstrap.verify(IMAGE, policy, changed, binary, root)
                    mocked.assert_not_called()

    def test_provenance_generator_checks_workflow_and_source(self):
        env = {"GITHUB_REPOSITORY": "jnbntc/distrobox-stack", "GITHUB_REF": "refs/heads/main",
               "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_REF": bootstrap.WORKFLOW,
               "GITHUB_SHA": "b" * 40, "GITHUB_WORKFLOW_SHA": "b" * 40,
               "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        self.assertEqual(maker.record(CONTRACT, env)["source"]["commit"], "b" * 40)
        for key in ("GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA"):
            bad = dict(env, **{key: "wrong"})
            with self.subTest(key=key), self.assertRaises(maker.bootstrap.VerificationError):
                maker.record(CONTRACT, bad)


    def test_original_regression_sbom_provenance_projections_require_deny(self):
        # The previous verifier returned VERIFIED for all three cases with the
        # same mocked responses. Generic projection is not a dedicated signature.
        for kinds in ([bootstrap.SPDX], [bootstrap.PROVENANCE],
                      [bootstrap.SPDX, bootstrap.PROVENANCE]):
            with self.subTest(kinds=kinds), fixture_verification_inputs() as inputs:
                responses = fixture_responses()
                responses[0] = fixture_generic_projection(kinds)
                with mock.patch.object(bootstrap, "invoke", side_effect=responses) as calls:
                    with self.assertRaises(bootstrap.VerificationError):
                        bootstrap.verify(IMAGE, *inputs)
                    self.assertEqual(calls.call_count, 1)

    def test_only_sbom_and_provenance_without_image_signature_denied(self):
        with fixture_verification_inputs() as inputs:
            responses = fixture_responses()
            responses[0] = responses[1] + "\n" + responses[2]
            with mock.patch.object(bootstrap, "invoke", side_effect=responses) as calls:
                with self.assertRaisesRegex(bootstrap.VerificationError, "predicate type"):
                    bootstrap.verify(IMAGE, *inputs)
                self.assertEqual(calls.call_count, 1)

    def test_attestation_cannot_be_relabelled_as_dedicated_signature(self):
        for predicate in (fixture_sbom(), fixture_provenance()):
            statement = fixture_signature_statement()
            statement["predicate"] = predicate
            raw = json.dumps({"payloadType": "application/vnd.in-toto+json",
                              "payload": base64.b64encode(json.dumps(statement).encode()).decode()})
            with self.subTest(predicate=predicate), self.assertRaises(bootstrap.VerificationError):
                bootstrap.signature_claims(raw, IMAGE)

    def test_signature_requires_native_v1_type_and_signed_repository(self):
        with self.assertRaises(bootstrap.VerificationError):
            bootstrap.signature_claims(fixture_generic_projection([bootstrap.IMAGE_SIGNATURE]), IMAGE)
        for mode in ("missing-annotation", "wrong-repository", "wrong-name", "missing-type", "legacy-type"):
            statement = fixture_signature_statement()
            subject = statement["subject"][0]
            if mode == "missing-annotation": del subject["annotations"]
            if mode == "wrong-repository": subject["annotations"][bootstrap.REPOSITORY_ANNOTATION] = "other"
            if mode == "wrong-name": subject["name"] = "other"
            if mode == "missing-type": del statement["predicateType"]
            if mode == "legacy-type": statement["_type"] = "https://in-toto.io/Statement/v0.1"
            raw = json.dumps({"payloadType": "application/vnd.in-toto+json",
                              "payload": base64.b64encode(json.dumps(statement).encode()).decode()})
            with self.subTest(mode=mode), self.assertRaises(bootstrap.VerificationError):
                bootstrap.signature_claims(raw, IMAGE)

    def test_missing_or_empty_signature_output_denied(self):
        for raw in ("", " ", "[]", "{}", "null"):
            with self.subTest(raw=raw), fixture_verification_inputs() as inputs:
                responses = fixture_responses()
                responses[0] = raw
                with mock.patch.object(bootstrap, "invoke", side_effect=responses):
                    with self.assertRaises(bootstrap.VerificationError):
                        bootstrap.verify(IMAGE, *inputs)

    def test_duplicate_or_malformed_evidence_denied_in_each_role(self):
        for position in range(3):
            for mode in ("duplicate", "same-statement-new-envelope", "malformed", "duplicate-json-key", "no-separator"):
                with self.subTest(position=position, mode=mode), fixture_verification_inputs() as inputs:
                    responses = fixture_responses()
                    raw = responses[position]
                    if mode == "duplicate": raw = raw + "\n" + raw
                    if mode == "same-statement-new-envelope":
                        other = json.loads(raw)
                        other["signatures"] = [{"sig": "fixture-only"}]
                        raw = raw + "\n" + json.dumps(other)
                    if mode == "malformed": raw = '{"payload":'
                    if mode == "duplicate-json-key": raw = '{"payload":"a","payload":"b"}'
                    if mode == "no-separator": raw = raw + raw
                    responses[position] = raw
                    with mock.patch.object(bootstrap, "invoke", side_effect=responses):
                        with self.assertRaises(bootstrap.VerificationError):
                            bootstrap.verify(IMAGE, *inputs)

    def test_wrong_signature_identity_rejected_by_cosign_denies_pipeline(self):
        # Simulate Cosign's cryptographic identity rejection, not a real cert.
        with fixture_verification_inputs() as inputs:
            failure = subprocess.CalledProcessError(1, "cosign", stderr="certificate identity mismatch")
            with mock.patch.object(bootstrap.subprocess, "run", side_effect=failure) as run:
                with self.assertRaises(bootstrap.VerificationError):
                    bootstrap.verify(IMAGE, *inputs)
                command = run.call_args.args[0]
                self.assertEqual(command[command.index("--certificate-identity") + 1], bootstrap.IDENTITY)
                self.assertEqual(command[command.index("--certificate-oidc-issuer") + 1], bootstrap.ISSUER)
                self.assertEqual(command[command.index("--type") + 1], bootstrap.IMAGE_SIGNATURE)
                self.assertEqual(run.call_count, 1)

    def test_failure_of_any_of_three_verifications_denies_pipeline(self):
        for position in range(3):
            with self.subTest(position=position), fixture_verification_inputs() as inputs:
                responses = fixture_responses()
                completed = [subprocess.CompletedProcess("fixture", 0, stdout=raw, stderr="")
                             for raw in responses[:position]]
                completed.append(subprocess.CalledProcessError(1, "cosign"))
                with mock.patch.object(bootstrap.subprocess, "run", side_effect=completed) as run:
                    with self.assertRaises(bootstrap.VerificationError):
                        bootstrap.verify(IMAGE, *inputs)
                    self.assertEqual(run.call_count, position + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
