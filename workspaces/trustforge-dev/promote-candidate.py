#!/usr/bin/env python3
"""Validate the reviewed candidate offline; never build, publish or run its code."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


bootstrap = module("promotion_bootstrap", "verify-bootstrap.py")
maker = module("promotion_builder", "make-provenance.py")
require = bootstrap.require
CANDIDATE = bootstrap.strict_json((HERE / "promotion-candidate.json").read_text())
WORKFLOW = "jnbntc/distrobox-stack/.github/workflows/trustforge-promote.yml@refs/heads/main"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def confirmation(candidate=CANDIDATE):
    c = candidate
    return (f"PROMOTE {c['repository']} run={c['run_id']} attempt={c['attempt']} "
            f"artifact={c['artifact_id']} source={c['source_commit']} "
            f"tar=sha256:{c['tar_sha256']} manifest={c['manifest_digest']}")


def context(env):
    require(env.get("GITHUB_REPOSITORY") == CANDIDATE["repository"], "wrong promotion repository")
    require(env.get("GITHUB_REF") == "refs/heads/main", "promotion requires main")
    require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "promotion requires manual dispatch")
    require(env.get("GITHUB_WORKFLOW_REF") == WORKFLOW, "wrong promotion workflow")
    sha = env.get("GITHUB_SHA", "")
    require(bootstrap.COMMIT.fullmatch(sha), "invalid promotion commit")
    require(env.get("GITHUB_WORKFLOW_SHA") == sha, "promotion workflow/checkout mismatch")
    require(env.get("TF_PROMOTION_CONFIRMATION") == confirmation(), "exact candidate confirmation required")
    run = {"run_id": env.get("GITHUB_RUN_ID", ""), "attempt": env.get("GITHUB_RUN_ATTEMPT", "")}
    require(all(re.fullmatch(r"[1-9][0-9]*", v) for v in run.values()), "invalid promotion invocation")
    # Re-runs must require a new dispatch and protected-environment review.
    require(run["attempt"] == "1", "promotion reruns forbidden")
    return {"workflow": {"id": "https://github.com/" + WORKFLOW,
            "workflow_ref": WORKFLOW, "workflow_sha": sha, "event": "workflow_dispatch"},
            "invocation": run, "candidate": CANDIDATE}


def origin(run, artifact, jobs, candidate=CANDIDATE):
    c = candidate
    require(run.get("id") == c["run_id"] and run.get("run_attempt") == c["attempt"], "wrong source run/attempt")
    require(run.get("repository", {}).get("full_name") == c["repository"]
            and run.get("repository", {}).get("id") == c["repository_id"], "external repository denied")
    require(run.get("head_repository", {}).get("id") == c["repository_id"], "fork build denied")
    require(run.get("head_sha") == c["source_commit"] and run.get("head_branch") == "main", "wrong source revision")
    require(run.get("path") == ".github/workflows/trustforge-dev.yml"
            and run.get("event") == "workflow_dispatch", "wrong source workflow/event")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "source build not successful")
    require(artifact.get("id") == c["artifact_id"] and artifact.get("name") == c["artifact_name"], "wrong artifact")
    require(artifact.get("expired") is False and artifact.get("size_in_bytes") == c["artifact_size"], "expired or changed artifact")
    require(artifact.get("digest") == "sha256:" + c["artifact_sha256"], "artifact digest mismatch")
    source = artifact.get("workflow_run", {})
    require(source.get("id") == c["run_id"] and source.get("head_sha") == c["source_commit"]
            and source.get("repository_id") == c["repository_id"]
            and source.get("head_repository_id") == c["repository_id"], "artifact source mismatch")
    rows = jobs.get("jobs", [])
    require(jobs.get("total_count") == 2 and len(rows) == 2, "unexpected source jobs")
    require({j.get("name") for j in rows} == {"build", "publish"}, "missing/duplicate source job")
    for job in rows:
        require(job.get("run_id") == c["run_id"] and job.get("run_attempt") == c["attempt"], "job invocation mismatch")
        require(job.get("status") == "completed", "unfinished source job")
        require(job.get("conclusion") == ("success" if job["name"] == "build" else "skipped"), "unexpected source job result")


def source_record(record, contract, candidate=CANDIDATE):
    c = candidate
    env = {"GITHUB_REPOSITORY": c["repository"], "GITHUB_REF": "refs/heads/main",
           "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_REF": bootstrap.WORKFLOW,
           "GITHUB_SHA": c["source_commit"], "GITHUB_WORKFLOW_SHA": c["source_commit"],
           "GITHUB_RUN_ID": str(c["run_id"]), "GITHUB_RUN_ATTEMPT": str(c["attempt"])}
    require(record == maker.record(contract, env), "inconsistent original build evidence")
    require(record["parameters"]["platform"] == c["platform"], "wrong candidate platform")
    require(record["materials"]["base_image"].endswith("@" + c["base_manifest_digest"]), "wrong Fedora base")


def check_tar(path, candidate=CANDIDATE):
    c = candidate
    with tarfile.open(path, "r:") as archive:
        members = {}
        for member in archive.getmembers():
            p = PurePosixPath(member.name)
            require(not p.is_absolute() and ".." not in p.parts, "unsafe OCI path")
            require(str(p) not in members and (member.isfile() or member.isdir()), "ambiguous OCI member")
            members[str(p)] = member

        def read(name, limit=2*1024*1024):
            item = members[name]
            require(item.isfile() and item.size <= limit, "unexpected OCI metadata size/type")
            return archive.extractfile(item).read()

        def blob(desc):
            value = desc["digest"]
            require(re.fullmatch(r"sha256:[0-9a-f]{64}", value), "unsupported OCI digest")
            name = "blobs/sha256/" + value[7:]
            item = members[name]
            require(item.isfile() and item.size == desc["size"], "OCI blob length mismatch")
            with archive.extractfile(item) as stream:
                require("sha256:" + hashlib.file_digest(stream, "sha256").hexdigest() == value, "OCI blob digest mismatch")
            return name

        require(bootstrap.strict_json(read("oci-layout").decode())["imageLayoutVersion"] == "1.0.0", "wrong OCI layout")
        index = bootstrap.strict_json(read("index.json").decode())
        require(index.get("schemaVersion") == 2 and len(index["manifests"]) == 1, "ambiguous OCI index")
        desc = index["manifests"][0]
        require(desc["digest"] == c["manifest_digest"]
                and desc["mediaType"] == "application/vnd.oci.image.manifest.v1+json", "candidate manifest mismatch")
        manifest = bootstrap.strict_json(read(blob(desc)).decode())
        require(manifest["schemaVersion"] == 2 and manifest["config"]["digest"] == c["config_digest"], "candidate config mismatch")
        config = bootstrap.strict_json(read(blob(manifest["config"])).decode())
        require(config["os"] == "linux" and config["architecture"] == "amd64", "wrong OCI platform")
        labels = config["config"]["Labels"]
        require(labels.get("org.opencontainers.image.revision") == c["source_commit"]
                and labels.get("org.opencontainers.image.source") == "https://github.com/" + c["repository"], "OCI source label mismatch")
        require(labels.get("org.opencontainers.image.vendor") == "Fedora Project"
                and labels.get("org.opencontainers.image.version") == "44", "not Fedora Toolbox 44")
        require(manifest["layers"][0]["digest"] == c["base_layer_digest"], "Fedora base layer mismatch")
        for layer in manifest["layers"]:
            blob(layer)
    return {"manifest_digest": desc["digest"], "config_digest": manifest["config"]["digest"], "platform": c["platform"]}


def validate(directory, output, contract, candidate=CANDIDATE):
    c = candidate
    origin(*(bootstrap.strict_json((directory / name).read_text()) for name in
             ("source-run.json", "source-artifact.json", "source-jobs.json")), candidate=c)
    zip_path = directory / "candidate.zip"
    require(zip_path.stat().st_size == c["artifact_size"] and digest(zip_path) == c["artifact_sha256"], "candidate ZIP hash mismatch")
    output.mkdir(mode=0o700)
    expected = {"trustforge-dev.oci.tar": c["tar_size"], "workspace.build.json": 1118, "candidate.sha256": 176}
    with zipfile.ZipFile(zip_path) as archive:
        rows = archive.infolist()
        require(len(rows) == 3 and {i.filename for i in rows} == set(expected), "unexpected ZIP files")
        for item in rows:
            require(item.file_size == expected[item.filename] and not item.is_dir()
                    and not item.flag_bits & 1 and (item.external_attr >> 16) & 0o170000 in (0, 0o100000), "unsafe ZIP member")
            target = output / item.filename
            with archive.open(item) as src, target.open("xb") as dst:
                os.chmod(target, 0o600)
                while chunk := src.read(1024*1024):
                    dst.write(chunk)
    # Always hash complete bytes before inspecting OCI or allowing publication.
    require(digest(output / "trustforge-dev.oci.tar") == c["tar_sha256"], "candidate tar hash mismatch")
    require(digest(output / "workspace.build.json") == c["build_record_sha256"], "build record hash mismatch")
    checks = {}
    for line in (output / "candidate.sha256").read_text().splitlines():
        parts = line.split()
        require(len(parts) == 2 and parts[1] not in checks, "ambiguous checksum evidence")
        checks[parts[1]] = parts[0]
    require(checks == {"trustforge-dev.oci.tar": c["tar_sha256"], "workspace.build.json": c["build_record_sha256"]}, "inconsistent checksum evidence")
    record = bootstrap.strict_json((output / "workspace.build.json").read_text())
    source_record(record, contract, c)
    return check_tar(output / "trustforge-dev.oci.tar", c)


def provenance(record, contract, env, image):
    promotion = context(env)
    require(image == bootstrap.REPOSITORY + "@" + CANDIDATE["manifest_digest"], "published manifest differs from reviewed candidate")
    source_record(record, contract)
    return {**record, "artifact": image, "promotion": promotion}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("confirmation", "origin", "validate", "provenance"))
    parser.add_argument("--directory", type=Path, default=Path("promotion-input"))
    parser.add_argument("--output", type=Path, default=Path("candidate"))
    parser.add_argument("--image")
    args = parser.parse_args()
    try:
        if args.mode == "confirmation":
            print(confirmation()); return 0
        context(os.environ)
        contract = bootstrap.strict_json((HERE / "contract.json").read_text())
        if args.mode == "origin":
            origin(*(bootstrap.strict_json((args.directory / n).read_text()) for n in
                     ("source-run.json", "source-artifact.json", "source-jobs.json")))
            result = {"origin": "PASS"}
        elif args.mode == "validate":
            result = validate(args.directory, args.output, contract)
        else:
            result = provenance(bootstrap.strict_json((args.output / "workspace.build.json").read_text()), contract, os.environ, args.image)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, KeyError, IndexError, TypeError, AttributeError, UnicodeError, tarfile.TarError, zipfile.BadZipFile) as error:
        # Never echo confirmation input, downloaded values or credentials.
        print("DENY: candidate promotion validation failed (" + type(error).__name__ + ")", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
