#!/usr/bin/env python3
"""Prepare workflow-asserted provenance after a future successful build/push.
This JSON is not authenticated until Cosign attests it; it is not SLSA certification.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bootstrap_verifier", HERE / "verify-bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def record(contract, env):
    bootstrap.require(env.get("GITHUB_REPOSITORY") == "jnbntc/distrobox-stack", "wrong build repository")
    bootstrap.require(env.get("GITHUB_REF") == "refs/heads/main", "wrong build ref")
    bootstrap.require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "wrong build event")
    bootstrap.require(env.get("GITHUB_WORKFLOW_REF") == bootstrap.WORKFLOW, "wrong workflow")
    source = env.get("GITHUB_SHA", "")
    bootstrap.require(bootstrap.COMMIT.fullmatch(source), "invalid source commit")
    bootstrap.require(env.get("GITHUB_WORKFLOW_SHA") == source, "workflow and checkout commit differ")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        bootstrap.require(re.fullmatch(r"[1-9][0-9]*", env.get(key, "")), "missing invocation")
    bootstrap.require(hashlib.sha256((HERE / "requirements.lock").read_bytes()).hexdigest() == contract["requirements"]["sha256"], "tool lock mismatch")
    return {
        "schema_version": 1,
        "source": {"repository": "https://github.com/jnbntc/distrobox-stack", "commit": source, "ref": "refs/heads/main"},
        "builder": {"id": bootstrap.IDENTITY, "workflow_ref": bootstrap.WORKFLOW,
                    "workflow_sha": source, "event": "workflow_dispatch"},
        "parameters": {"platform": contract["platform"],
                       "containerfile": "workspaces/trustforge-dev/Containerfile",
                       "image_repository": bootstrap.REPOSITORY},
        "materials": bootstrap.expected_materials(contract),
        "invocation": {"run_id": env["GITHUB_RUN_ID"], "attempt": env["GITHUB_RUN_ATTEMPT"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--record-build", action="store_true")
    modes.add_argument("--build-record", type=Path)
    parser.add_argument("--image")
    args = parser.parse_args()
    try:
        contract = bootstrap.strict_json((HERE / "contract.json").read_text())
        current = record(contract, os.environ)
        if args.build_record:
            bootstrap.require(args.image is not None, "final image digest required")
            bootstrap.image_digest(args.image)
            previous = bootstrap.strict_json(args.build_record.read_text())
            bootstrap.require(previous == current, "build record does not match this source/workflow/run")
            current["artifact"] = args.image
        else:
            bootstrap.require(args.image is None, "image is only valid after publication")
        print(json.dumps(current, sort_keys=True))
    except (bootstrap.VerificationError, OSError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
