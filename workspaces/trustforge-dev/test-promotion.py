#!/usr/bin/env python3
"""Offline promotion regression tests. No registry, Cosign or workflow execution."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("promotion", HERE / "promote-candidate.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
b = p.bootstrap
C = p.CANDIDATE
CONTRACT = b.strict_json((HERE / "contract.json").read_text())


def environment():
    return {"GITHUB_REPOSITORY": C["repository"], "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_REF": p.WORKFLOW,
            "GITHUB_SHA": "b" * 40, "GITHUB_WORKFLOW_SHA": "b" * 40,
            "GITHUB_RUN_ID": "777", "GITHUB_RUN_ATTEMPT": "1",
            "TF_PROMOTION_CONFIRMATION": p.confirmation()}


def record():
    env = {"GITHUB_REPOSITORY": C["repository"], "GITHUB_REF": "refs/heads/main",
           "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_REF": b.WORKFLOW,
           "GITHUB_SHA": C["source_commit"], "GITHUB_WORKFLOW_SHA": C["source_commit"],
           "GITHUB_RUN_ID": str(C["run_id"]), "GITHUB_RUN_ATTEMPT": "1"}
    return p.maker.record(CONTRACT, env)


def policy():
    value = b.strict_json((HERE / "promotion-policy.example.json").read_text())
    return {**value, "approved": True, "signer_commit": "b" * 40, "trusted_root_sha256": "c" * 64}


def metadata(c):
    run = {"id": c["run_id"], "run_attempt": c["attempt"], "head_sha": c["source_commit"],
           "head_branch": "main", "repository": {"full_name": c["repository"], "id": c["repository_id"]},
           "head_repository": {"id": c["repository_id"]}, "path": ".github/workflows/trustforge-dev.yml",
           "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
    artifact = {"id": c["artifact_id"], "name": c["artifact_name"], "expired": False,
                "size_in_bytes": c["artifact_size"], "digest": "sha256:"+c["artifact_sha256"],
                "workflow_run": {"id": c["run_id"], "head_sha": c["source_commit"],
                                 "repository_id": c["repository_id"], "head_repository_id": c["repository_id"]}}
    jobs = {"total_count": 2, "jobs": [{"name": name, "run_id": c["run_id"], "run_attempt": 1,
            "status": "completed", "conclusion": result} for name, result in (("build", "success"), ("publish", "skipped"))]}
    return run, artifact, jobs


def fixture(directory, mutate=None):
    """Small synthetic OCI transport fixture, not a built or signed image."""
    c = copy.deepcopy(C)
    files = {}
    def blob(raw):
        h = hashlib.sha256(raw).hexdigest(); files["blobs/sha256/"+h] = raw
        return {"digest": "sha256:"+h, "size": len(raw)}
    config = {"os": "linux", "architecture": "amd64", "config": {"Labels": {
        "org.opencontainers.image.revision": c["source_commit"],
        "org.opencontainers.image.source": "https://github.com/"+c["repository"],
        "org.opencontainers.image.vendor": "Fedora Project", "org.opencontainers.image.version": "44"}}}
    config_desc = blob(json.dumps(config).encode()); c["config_digest"] = config_desc["digest"]
    layer = blob(b"synthetic layer bytes; never executed"); c["base_layer_digest"] = layer["digest"]
    manifest = {"schemaVersion": 2, "config": config_desc, "layers": [layer]}
    if mutate: mutate(manifest, config, files)
    c["config_digest"] = manifest["config"]["digest"]
    desc = blob(json.dumps(manifest).encode()); desc["mediaType"] = "application/vnd.oci.image.manifest.v1+json"
    c["manifest_digest"] = desc["digest"]
    files["index.json"] = json.dumps({"schemaVersion": 2, "manifests": [desc]}).encode()
    files["oci-layout"] = b'{"imageLayoutVersion":"1.0.0"}'
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, raw in files.items():
            info = tarfile.TarInfo(name); info.size = len(raw); tar.addfile(info, io.BytesIO(raw))
    raw_tar = stream.getvalue(); c["tar_size"] = len(raw_tar); c["tar_sha256"] = hashlib.sha256(raw_tar).hexdigest()
    raw_record = (json.dumps(record(), sort_keys=True)+"\n").encode()
    assert len(raw_record) == 1118
    c["build_record_sha256"] = hashlib.sha256(raw_record).hexdigest()
    checks = f"{c['tar_sha256']}  trustforge-dev.oci.tar\n{c['build_record_sha256']}  workspace.build.json\n".encode()
    path = directory / "candidate.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, raw in (("trustforge-dev.oci.tar", raw_tar), ("workspace.build.json", raw_record), ("candidate.sha256", checks)):
            z.writestr(name, raw)
    c["artifact_size"] = path.stat().st_size; c["artifact_sha256"] = p.digest(path)
    for name, value in zip(("source-run.json", "source-artifact.json", "source-jobs.json"), metadata(c)):
        (directory/name).write_text(json.dumps(value))
    return c


class Promotion(unittest.TestCase):
    def test_exact_confirmation_and_context(self):
        self.assertEqual(p.context(environment())["candidate"], C)
        for field in environment():
            with self.subTest(field=field), self.assertRaises(b.VerificationError):
                env = environment(); env[field] += "changed"; p.context(env)

    def test_origin_and_external_candidate_negatives(self):
        p.origin(*metadata(C))
        changes = [(0,"id",1), (0,"run_attempt",2), (0,"head_sha","a"*40),
                   (0,"event","pull_request"), (0,"path",".github/workflows/other.yml"),
                   (0,"repository",{"full_name":"attacker/repo","id":1}),
                   (0,"head_repository",{"id":1}), (0,"conclusion","failure"),
                   (1,"id",1), (1,"expired",True), (1,"digest","sha256:"+"0"*64),
                   (1,"workflow_run",{}), (2,"total_count",3)]
        for index, key, value in changes:
            with self.subTest(key=key), self.assertRaises(b.VerificationError):
                docs = metadata(C); docs[index][key] = value; p.origin(*docs)
        docs = metadata(C); docs[2]["jobs"][1]["conclusion"] = "success"
        with self.assertRaises(b.VerificationError): p.origin(*docs)

    def test_small_oci_fixture_complete_byte_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp); c = fixture(directory)
            result = p.validate(directory, directory/"out", CONTRACT, c)
            self.assertEqual(result["manifest_digest"], c["manifest_digest"])
            self.assertEqual(result["platform"], "linux/amd64")

    def test_wrong_zip_tar_and_build_record_hashes_deny(self):
        for field in ("artifact_sha256", "tar_sha256", "build_record_sha256"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp); c = fixture(directory); c[field] = "0"*64
                # Keep API metadata consistent: the full-byte check must deny.
                docs = metadata(c)
                (directory/"source-artifact.json").write_text(json.dumps(docs[1]))
                with self.assertRaises(b.VerificationError): p.validate(directory,directory/"out",CONTRACT,c)

    def test_inconsistent_original_evidence_denied(self):
        for field in ("source", "builder", "materials", "invocation", "parameters"):
            with self.subTest(field=field), self.assertRaises(b.VerificationError):
                value = record(); value[field] = {}; p.source_record(value,CONTRACT)

    def test_wrong_manifest_config_or_layer_denied(self):
        for field in ("manifest_digest", "config_digest", "base_layer_digest"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp); c = fixture(directory)
                p.validate(directory,directory/"out",CONTRACT,c)
                c[field] = "sha256:"+"0"*64
                with self.assertRaises(b.VerificationError): p.check_tar(directory/"out/trustforge-dev.oci.tar",c)

    def test_changed_source_or_platform_in_oci_config_denied(self):
        for field in ("architecture", "labels"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                def change(manifest, config, files):
                    if field == "architecture": config["architecture"] = "arm64"
                    else: config["config"]["Labels"]["org.opencontainers.image.revision"] = "a"*40
                    raw=json.dumps(config).encode(); h=hashlib.sha256(raw).hexdigest()
                    files['blobs/sha256/'+h]=raw
                    manifest['config']={'digest':'sha256:'+h,'size':len(raw)}
                directory=Path(temp);c=fixture(directory,change)
                with self.assertRaises(b.VerificationError):p.validate(directory,directory/'out',CONTRACT,c)

    def test_unsafe_zip_and_inconsistent_checksum_evidence_denied(self):
        for mode in ('path','duplicate','checksum'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);c=fixture(directory);path=directory/'candidate.zip'
                with zipfile.ZipFile(path) as z:contents={i.filename:z.read(i) for i in z.infolist()}
                if mode=='path':contents['../escape']=b'no'
                if mode=='checksum':contents['candidate.sha256']=contents['candidate.sha256'].replace(c['tar_sha256'].encode(),b'0'*64)
                with zipfile.ZipFile(path,'w') as z:
                    for name,raw in contents.items():z.writestr(name,raw)
                    if mode=='duplicate':z.writestr('candidate.sha256',contents['candidate.sha256'])
                c['artifact_size']=path.stat().st_size;c['artifact_sha256']=p.digest(path)
                (directory/'source-artifact.json').write_text(json.dumps(metadata(c)[1]))
                with self.assertRaises(b.VerificationError):p.validate(directory,directory/'out',CONTRACT,c)

    def test_promotion_keeps_build_source_and_separates_signer(self):
        image = b.REPOSITORY+"@"+C["manifest_digest"]
        value = p.provenance(record(),CONTRACT,environment(),image)
        self.assertEqual(value["source"]["commit"], C["source_commit"])
        self.assertEqual(value["builder"]["workflow_sha"], C["source_commit"])
        self.assertEqual(value["promotion"]["workflow"]["workflow_sha"],"b"*40)
        sbom = {"spdxVersion":"SPDX-2.3","SPDXID":"SPDXRef-DOCUMENT","documentNamespace":"fixture","packages":[{"name":"fixture"}]}
        b.check_predicates([sbom],[value],policy(),CONTRACT,image)
        for field in ("workflow","candidate","invocation"):
            with self.subTest(field=field),self.assertRaises(b.VerificationError):
                changed=copy.deepcopy(value);changed["promotion"][field]={}
                b.check_predicates([sbom],[changed],policy(),CONTRACT,image)
        with self.assertRaises(b.VerificationError):p.provenance(record(),CONTRACT,environment(),b.REPOSITORY+"@sha256:"+"0"*64)

    def test_schema2_requires_new_explicit_approval_and_exact_crypto_binding(self):
        template=b.strict_json((HERE/"promotion-policy.example.json").read_text())
        with self.assertRaises(b.VerificationError):b.check_policy(template)
        b.check_policy(policy())
        for field in ("source_commit","signer_commit","identity","trusted_root_sha256"):
            with self.subTest(field=field),self.assertRaises(b.VerificationError):
                wrong=policy();wrong[field]="invalid";b.check_policy(wrong)
        commands=b.cosign_commands(Path('/trusted/cosign'),Path('/trusted/root'),policy(),b.REPOSITORY+"@"+C['manifest_digest'])
        self.assertEqual(len(commands),3)
        for command in commands:
            self.assertEqual(command[command.index('--certificate-github-workflow-sha')+1],"b"*40)
            self.assertIn(b.PROMOTION_IDENTITY,command)
            for flag in ('--check-claims=true','--insecure-ignore-tlog=false','--insecure-ignore-sct=false'):self.assertIn(flag,command)
        with self.assertRaises(b.VerificationError):b.cosign_commands(Path('/trusted/cosign'),Path('/trusted/root'),policy(),b.REPOSITORY+'@sha256:'+'0'*64)

    def test_workflow_permissions_order_and_no_build(self):
        w=b.strict_json((HERE.parents[1]/'.github/workflows/trustforge-promote.yml').read_text())
        self.assertEqual(set(w['on']),{'workflow_dispatch'})
        self.assertTrue(w['on']['workflow_dispatch']['inputs']['confirmation']['required'])
        self.assertEqual(w['permissions'],{'contents':'read'})
        read,publish=w['jobs']['validate'],w['jobs']['publish']
        self.assertEqual(read['permissions'],{'contents':'read','actions':'read'})
        self.assertEqual(publish['environment'],'trustforge-bootstrap-publish')
        self.assertEqual(publish['needs'],'validate')
        for job in (read,publish):
            self.assertEqual(job['if'],"github.ref == 'refs/heads/main'")
            self.assertEqual(job['steps'][0]['with'],{'persist-credentials':False})
            for step in job['steps']:
                if 'uses' in step:self.assertRegex(step['uses'],r'^[\w/-]+@[0-9a-f]{40}$')
                if 'run' in step:
                    subprocess.run(['bash','-n'],input=step['run'],text=True,check=True)
                    self.assertNotRegex(step['run'],r'\b(podman|docker|buildah)\s+(build|run|load)\b')
                    self.assertNotIn('${{ inputs.',step['run'])
        self.assertIn('origin\ngh api',read['steps'][1]['run'])
        self.assertIn('/artifacts/13098563945/zip',read['steps'][1]['run'])
        self.assertIn('validate',publish['steps'][2]['run'])
        script=publish['steps'][5]['run']
        self.assertIn('--preserve-digests --digestfile',script)
        self.assertLess(script.index('sha256sum -c -'),script.index('skopeo login'))
        self.assertLess(script.index('published.manifest.json | sha256sum -c -'),script.index('cosign sign'))
        self.assertEqual(script.count('cosign attest --yes'),2)
        self.assertIn('io.trustforge.repository=ghcr.io/jnbntc/trustforge-dev',script)

    def test_publisher_auth_is_shared_private_and_not_uploaded(self):
        workflow=b.strict_json((HERE.parents[1]/'.github/workflows/trustforge-promote.yml').read_text())
        read,publish=workflow['jobs']['validate'],workflow['jobs']['publish']
        self.assertNotIn('GHCR_TOKEN',json.dumps(read))
        self.assertEqual(publish['permissions'],{'contents':'read','actions':'read','packages':'write','id-token':'write'})
        self.assertEqual([i for i,s in enumerate(publish['steps']) if 'GHCR_TOKEN' in s.get('env',{})],[5])
        script=publish['steps'][5]['run']
        self.assertIn('export DOCKER_CONFIG="$authdir"',script)
        self.assertIn('authfile="$DOCKER_CONFIG/config.json"',script)
        self.assertIn('umask 077',script)
        self.assertIn('chmod 700 "$authdir"',script)
        self.assertIn('chmod 600 "$authfile"',script)
        self.assertIn("trap 'rm -rf -- \"$authdir\"' EXIT",script)
        self.assertLess(script.index("trap 'rm -rf"),script.index('printf \'%s\' "$GHCR_TOKEN"'))
        self.assertLess(script.index('export DOCKER_CONFIG'),script.index('skopeo login'))
        self.assertIn('skopeo login --authfile "$authfile" --username "$GHCR_ACTOR" --password-stdin ghcr.io',script)
        self.assertNotIn('--registry-password',script)
        self.assertNotIn('set -x',script)
        for step in publish['steps']:
            if step.get('uses','').startswith('actions/upload-artifact@'):
                for forbidden in ('authdir','authfile','config.json','RUNNER_TEMP','DOCKER_CONFIG'):
                    self.assertNotIn(forbidden,step['with']['path'])

    def test_auth_block_propagation_permissions_and_cleanup_without_real_tools(self):
        # Exercise only shell auth setup with a local login stub and dummy data.
        # Neither Cosign, Syft, Skopeo, a registry nor a real token is used.
        w=b.strict_json((HERE.parents[1]/'.github/workflows/trustforge-promote.yml').read_text())
        script=w['jobs']['publish']['steps'][5]['run']
        block=script[script.index('set +x'):script.index('\nskopeo copy')]
        stub='''set -euo pipefail
skopeo() {
  test "$1" = login
  test "$2" = --authfile
  test "$3" = "$DOCKER_CONFIG/config.json"
  test "$6" = --password-stdin
  printf '%s' "$DOCKER_CONFIG" > "$OBSERVED_PATH"
  python3 -c 'import json,os,sys; from pathlib import Path; p=Path(os.environ["DOCKER_CONFIG"]); assert p.stat().st_mode & 0o777 == 0o700; f=p/"config.json"; assert f.stat().st_mode & 0o777 == 0o600; value=sys.stdin.read(); assert value==os.environ["GHCR_TOKEN"]; f.write_text(json.dumps({"auths":{"ghcr.io":{"auth":"fixture-only-not-a-credential"}}}))'
  if test "$AUTH_CASE" = login-failure; then return 23; fi
}
'''
        child='''
python3 -c 'import json,os; from pathlib import Path; p=Path(os.environ["DOCKER_CONFIG"]); assert p.stat().st_mode & 0o777 == 0o700; f=p/"config.json"; assert f.stat().st_mode & 0o777 == 0o600; assert json.loads(f.read_text())["auths"]["ghcr.io"]["auth"]=="fixture-only-not-a-credential"'
if test "$AUTH_CASE" = later-failure; then exit 19; fi
if test "$AUTH_CASE" = term; then kill -TERM $$; fi
'''
        for mode,code in [('success',0),('login-failure',23),('later-failure',19),('term',143)]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                directory=Path(temp); observed=directory/'observed-path'
                env={**os.environ,'RUNNER_TEMP':temp,'GHCR_ACTOR':'fixture-user',
                     'GHCR_TOKEN':'fixture-only-not-a-token','OBSERVED_PATH':str(observed),'AUTH_CASE':mode}
                result=subprocess.run(['bash'],input=stub+block+child,env=env,text=True,capture_output=True)
                self.assertEqual(result.returncode,code,result.stderr)
                authdir=Path(observed.read_text())
                self.assertEqual(authdir.parent,directory)
                self.assertFalse(authdir.exists(),'credential directory survived EXIT trap')
                self.assertNotIn(env['GHCR_TOKEN'],result.stdout+result.stderr)
                self.assertNotIn('fixture-only-not-a-credential',result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
