#!/usr/bin/env python3
"""Check manual operator intent only; never verify, build, publish or deploy."""
import json
import os
import re
import sys

WORKFLOW = "jnbntc/distrobox-stack/.github/workflows/trustforge-dev.yml@refs/heads/main"


def check(env):
    expected_context = {
        "GITHUB_REPOSITORY": "jnbntc/distrobox-stack",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
    }
    if any(env.get(key) != value for key, value in expected_context.items()):
        raise ValueError("Publication intent rejected: unexpected workflow context")
    source = env.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source) or env.get("GITHUB_WORKFLOW_SHA") != source:
        raise ValueError("Publication intent rejected: source/workflow commit mismatch")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not re.fullmatch(r"[1-9][0-9]*", env.get(key, "")):
            raise ValueError("Publication intent rejected: missing invocation identity")
    publish = env.get("TF_PUBLISH")
    if publish not in ("true", "false"):
        raise ValueError("Publication intent rejected: invalid publish input")
    if publish == "true" and env.get("TF_PUBLICATION_CONFIRMATION") != f"PUBLISH {WORKFLOW} {source}":
        raise ValueError("Publication intent rejected: confirmation must match workflow/ref/commit exactly")
    return {
        "publish": publish == "true",
        "publication_intent_confirmed": publish == "true",
        "workflow_ref": WORKFLOW,
        "source_commit": source,
        "run_id": env["GITHUB_RUN_ID"],
        "run_attempt": env["GITHUB_RUN_ATTEMPT"],
        "cryptographic_verification": False,
        "deployment_authorized": False,
    }


def main():
    try:
        result = check(os.environ)
    except ValueError as error:
        # Never echo the supplied confirmation or arbitrary environment values.
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
