#!/usr/bin/env python3
"""Render ONE manifest to stdout. No runtime calls, writes or trust verification."""
import argparse
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
IMAGE = re.compile(r"ghcr\.io/jnbntc/trustforge-dev@sha256:[0-9a-f]{64}")
HOME = re.compile(r"/[A-Za-z0-9_./-]+")


def render(image: str, home: str) -> str:
    if not IMAGE.fullmatch(image):
        raise ValueError("Expected ghcr.io/jnbntc/trustforge-dev@sha256:<64 lowercase hex>")
    if not HOME.fullmatch(home) or ".." in Path(home).parts:
        raise ValueError("host-home must be an absolute path without spaces, shell syntax or '..'")
    if home == "/" or home.endswith("/"):
        raise ValueError("host-home must name a home directory, without a trailing slash")
    template = (HERE / "distrobox.ini.in").read_text()
    values = {
        "@WORKSPACE_IMAGE@": image,
        "@HOST_HOME@": home,
        "@WORKSPACE_HOME@": home + "/.local/share/trustforge-dev/home",
        "@CACHE_DIR@": home + "/.cache/trustforge-dev",
    }
    for token, value in values.items():
        template = template.replace(token, value)
    if re.search(r"@[A-Z_]+@", template):
        raise ValueError("Unresolved manifest token")
    return template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Already verified output image by digest")
    parser.add_argument("--host-home", default=str(Path.home()))
    args = parser.parse_args()
    try:
        result = render(args.image, args.host_home)
    except ValueError as error:
        parser.error(str(error))
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
