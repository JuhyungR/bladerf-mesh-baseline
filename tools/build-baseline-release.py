#!/usr/bin/env python3
"""Offline release input verifier; it never contacts hardware or a remote."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from baseline_manifest import canonical_bytes, manifest_sha256, validate_manifest


APPROVED_TRACKED_PATHS = frozenset({
    ".gitattributes", ".gitignore", "LICENSE", "README.md", "SOURCE_OFFER.md",
    "THIRD_PARTY_NOTICES.md", "baseline_manifest.py", "pyproject.toml",
    "docs/manifest-format.md", "manifest/baseline-manifest.json",
    "schema/baseline-manifest.schema.json", "tools/bladerf-link-node",
    "tools/bladerf-project-admin", "tools/install-baseline-runtime",
    "tools/build-baseline-release.py",
    "systemd/bladerf-link-base.service", "systemd/bladerf-link-jetson.service",
    "configs/local/base.local-profile.example.json", "configs/local/jetson.local-profile.example.json",
    "tests/test_baseline_manifest.py", "tests/test_baseline_runtime_no_start.py",
    "tests/test_baseline_release_archive.py",
    "firmware/base/bladerf_wlan.rbf", "firmware/jetson/bladerf_wlan.rbf",
    "firmware/jetson/mac80211_hwsim.ko",
    "runtime/base/bladeRF-linux-mac80211.hwsim42",
    "runtime/jetson/bladeRF-linux-mac80211.hwsim42",
})


def validate_tracked_payload(paths: set[str]) -> None:
    if paths != APPROVED_TRACKED_PATHS:
        unexpected = sorted(paths - APPROVED_TRACKED_PATHS)
        missing = sorted(APPROVED_TRACKED_PATHS - paths)
        raise ValueError(f"tracked payload does not exactly match allowlist: unexpected={unexpected}; missing={missing}")


def tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "ls-files", "-z"],
        check=False, capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("cannot enumerate tracked payload")
    return {path.decode("utf-8") for path in result.stdout.split(b"\0") if path}


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_artifact_root(value: dict, artifact_root: Path, prefix: str) -> None:
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ValueError(f"{prefix} root must be a real directory")
    expected: dict[str, dict] = {}
    for artifact in value["artifacts"]:
        repo_path = Path(artifact["repo_path"])
        if not repo_path.parts or repo_path.parts[0] != prefix:
            continue
        relative = Path(*repo_path.parts[1:]).as_posix()
        expected[relative] = artifact
    observed: set[str] = set()
    for path in artifact_root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"{prefix} tree contains a symlink")
        if path.is_file():
            observed.add(path.relative_to(artifact_root).as_posix())
        elif not path.is_dir():
            raise ValueError(f"{prefix} tree contains a non-file leaf")
    if observed != set(expected):
        raise ValueError(
            f"{prefix} tree does not exactly match manifest: "
            f"unexpected={sorted(observed - set(expected))}; missing={sorted(set(expected) - observed)}"
        )
    for relative, artifact in expected.items():
        path = artifact_root / Path(relative)
        if path.stat().st_size != artifact["size_bytes"]:
            raise ValueError(f"{prefix} size mismatch: {relative}")
        if file_sha256(path) != artifact["sha256"]:
            raise ValueError(f"{prefix} SHA-256 mismatch: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--firmware-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        parser.error("only --verify-only is available before firmware extraction")
    manifest_bytes = args.manifest.read_bytes()
    value = json.loads(manifest_bytes.decode("utf-8"))
    validate_manifest(value)
    if manifest_bytes != canonical_bytes(value):
        raise SystemExit("manifest bytes are not canonical")
    validate_tracked_payload(tracked_paths())
    firmware_state = value["release"].get("firmware_state")
    if args.firmware_root is None and args.runtime_root is None:
        if firmware_state != "deferred":
            raise SystemExit("verified firmware state requires --firmware-root and --runtime-root")
        print("release_input_status=offline-schema-ok")
    else:
        if args.firmware_root is None or args.runtime_root is None:
            raise SystemExit("full artifact verification requires --firmware-root and --runtime-root")
        verify_artifact_root(value, args.firmware_root, "firmware")
        verify_artifact_root(value, args.runtime_root, "runtime")
        if value["release"]["runtime_state"] == "verified":
            print("release_input_status=verified")
        else:
            print("release_input_status=firmware-verified-runtime-deferred")
        print("firmware_state=verified")
        print("bridge_state=verified")
        print(f"runtime_state={value['release']['runtime_state']}")
    print(f"manifest_sha256={manifest_sha256(value)}")
    print(f"payload_count={len(APPROVED_TRACKED_PATHS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
