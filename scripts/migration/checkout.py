#!/usr/bin/env python3
"""Check out a migration bundle into a NEW directory, preserving shallow history.

Git bundles alone do not carry a shallow repository's history boundary. This
bootstrap imports only reachable bundle objects plus that boundary, never the
source .git directory's unreachable blobs, credentials or machine configuration.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def checkout(package, destination):
    if destination.exists():
        raise RuntimeError("Destination must not exist; no existing checkout is overwritten")
    manifest_path = package / "manifest.private.json"
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if manifest_hash != (package / "MANIFEST.sha256").read_text().strip():
        raise RuntimeError("Manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    branch, commit = manifest["source_branch"], manifest["source_commit"]
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", branch) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Invalid source reference")
    for filename in ("source.bundle", "source.shallow"):
        if filename not in manifest["files"]:
            if filename == "source.bundle":
                raise RuntimeError("Source bundle missing")
            continue
        with (package / filename).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["files"][filename]["sha256"]:
                raise RuntimeError(f"Checksum mismatch: {filename}")
    destination.mkdir(parents=True)

    def git(*args):
        return subprocess.check_output(["git", "-C", str(destination), *args], stderr=subprocess.STDOUT)

    git("init", "--initial-branch", branch)
    if "source.shallow" in manifest["files"]:
        shutil.copy2(package / "source.shallow", destination / ".git/shallow")
    git("bundle", "unbundle", str(package / "source.bundle"))
    git("update-ref", f"refs/heads/{branch}", commit)
    git("checkout", branch)
    if git("status", "--porcelain").strip():
        raise RuntimeError("Unexpected changes in new checkout")
    print(f"Offline checkout ready: {destination}; commit {commit[:8]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    checkout(args.package.resolve(), args.destination.resolve())
