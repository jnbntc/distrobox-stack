#!/usr/bin/env python3
"""Offline structural and negative checks; never invokes a container engine."""
import configparser
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("trustforge_manifest", HERE / "render-manifest.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
CONTRACT = json.loads((HERE / "contract.json").read_text())
IMAGE = CONTRACT["output"]["repository"] + "@sha256:" + "a" * 64


class WorkspaceContract(unittest.TestCase):
    def test_source_pins_and_target(self):
        text = (HERE / "Containerfile").read_text()
        for key in ("base", "uv"):
            pin = CONTRACT[key]["reference"] + "@" + CONTRACT[key]["manifest_digest"]
            self.assertIn("FROM " + pin, text)
        self.assertEqual(CONTRACT["platform"], "linux/amd64")
        self.assertIn("uv python install " + CONTRACT["python"]["selector"], text)
        self.assertNotIn("podman.sock", text)
        self.assertNotIn("docker.sock", text)

    def test_hashed_tool_lock(self):
        raw = (HERE / CONTRACT["requirements"]["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CONTRACT["requirements"]["sha256"])
        entries = re.split(r"\n(?=[a-zA-Z0-9_.-]+==)", raw.decode().strip())
        self.assertEqual(len(entries), 11)
        for entry in entries:
            self.assertRegex(entry, r"^[a-zA-Z0-9_.-]+==[^\s;]+")
            self.assertRegex(entry, r"--hash=sha256:[0-9a-f]{64}")
        for name, version in CONTRACT["tools"].items():
            self.assertRegex(raw.decode(), rf"(?m)^{re.escape(name)}=={re.escape(version)}(?:\s|$)")

    def test_manifest_only_new_rootless_workspace(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(renderer.render(IMAGE, "/tmp/fixture-home"))
        self.assertEqual(config.sections(), ["trustforge-dev"])
        entry = config["trustforge-dev"]
        self.assertEqual(entry["image"], IMAGE)
        for key in ("root", "replace", "pull", "start_now", "entry", "init", "nvidia"):
            self.assertEqual(entry[key], "false", key)
        self.assertEqual(entry["unshare_all"], "true")
        self.assertEqual(entry["volume"], '"/tmp/fixture-home/Proyectos/trustforge:/workspace/trustforge:rw"')
        flags = entry["additional_flags"]
        for forbidden in ("--privileged", "--cap-add", "--device", "label=disable", ".sock", ":z", ":Z"):
            self.assertNotIn(forbidden, flags)
        # This checks OUR manifest only, not Distrobox's implicit runtime flags.

    def test_reject_tag_foreign_repo_short_digest_and_injection(self):
        for image in ("ghcr.io/jnbntc/trustforge-dev:latest",
                      "ghcr.io/other/trustforge-dev@sha256:" + "a" * 64,
                      CONTRACT["output"]["repository"] + "@sha256:123",
                      IMAGE + "\nroot=true"):
            with self.subTest(image=image), self.assertRaises(ValueError):
                renderer.render(image, "/tmp/fixture-home")

    def test_reject_unsafe_paths(self):
        for home in ("/", "/tmp/../root", "/tmp/a b", "/tmp/a:b", "/tmp/$(id)", "/tmp/a\nroot=true", "relative"):
            with self.subTest(home=home), self.assertRaises(ValueError):
                renderer.render(IMAGE, home)

    def test_excluded_from_mass_operations(self):
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read(ROOT / "distrobox.ini")
        self.assertNotIn("trustforge-dev", config.sections())
        self.assertNotIn('"trustforge-dev"', (ROOT / "scripts/stack.sh").read_text())
        self.assertIsNone(CONTRACT["output"]["digest"])
        self.assertFalse(CONTRACT["deployment"]["approved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
