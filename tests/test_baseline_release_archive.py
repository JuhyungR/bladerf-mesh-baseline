from pathlib import Path
import importlib.util
import json
import subprocess


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "tools" / "build-baseline-release.py"

SPEC = importlib.util.spec_from_file_location("build_baseline_release", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_offline_release_verifier_accepts_deferred_firmware_only(tmp_path):
    value = json.loads((ROOT / "manifest/baseline-manifest.json").read_text(encoding="utf-8"))
    value["release"] = {"firmware_state": "deferred", "runtime_state": "deferred"}
    deferred = tmp_path / "deferred-manifest.json"
    deferred.write_bytes(MODULE.canonical_bytes(value))
    result = subprocess.run(
        ["python", str(TOOL), "--manifest", str(deferred), "--verify-only"],
        text=True, capture_output=True, cwd=ROOT, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "release_input_status=offline-schema-ok" in result.stdout
    assert "manifest_sha256=" in result.stdout


def test_verified_release_requires_and_validates_exact_firmware_tree():
    missing_root = subprocess.run(
        ["python", str(TOOL), "--manifest", "manifest/baseline-manifest.json", "--verify-only"],
        text=True, capture_output=True, cwd=ROOT, check=False,
    )
    assert missing_root.returncode != 0
    assert "requires --firmware-root and --runtime-root" in missing_root.stderr

    partial_root = subprocess.run(
        ["python", str(TOOL), "--manifest", "manifest/baseline-manifest.json", "--firmware-root", "firmware", "--verify-only"],
        text=True, capture_output=True, cwd=ROOT, check=False,
    )
    assert partial_root.returncode != 0
    assert "full artifact verification requires --firmware-root and --runtime-root" in partial_root.stderr

    verified = subprocess.run(
        ["python", str(TOOL), "--manifest", "manifest/baseline-manifest.json", "--firmware-root", "firmware", "--runtime-root", "runtime", "--verify-only"],
        text=True, capture_output=True, cwd=ROOT, check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert "release_input_status=verified" in verified.stdout
    assert "firmware_state=verified" in verified.stdout
    assert "bridge_state=verified" in verified.stdout
    assert "runtime_state=verified" in verified.stdout
    assert "payload_count=" in verified.stdout


def test_release_verifier_rejects_noncanonical_manifest_bytes(tmp_path):
    value = json.loads((ROOT / "manifest/baseline-manifest.json").read_text(encoding="utf-8"))
    noncanonical = tmp_path / "manifest.json"
    noncanonical.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(
        ["python", str(TOOL), "--manifest", str(noncanonical), "--firmware-root", "firmware", "--runtime-root", "runtime", "--verify-only"],
        text=True, capture_output=True, cwd=ROOT, check=False,
    )
    assert result.returncode != 0
    assert "not canonical" in result.stderr


def test_tracked_payload_allowlist_is_exact_and_rejects_an_extra_path():
    tracked = MODULE.tracked_paths()
    assert tracked == MODULE.APPROVED_TRACKED_PATHS
    try:
        MODULE.validate_tracked_payload(set(tracked) | {"unexpected/tracked-file"})
    except ValueError as error:
        assert "unexpected/tracked-file" in str(error)
    else:
        raise AssertionError("unexpected tracked path was accepted")


def test_runtime_tree_is_exact_and_bridge_tampering_is_rejected(tmp_path):
    runtime = tmp_path / "runtime"
    base = runtime / "base"
    jetson = runtime / "jetson"
    base.mkdir(parents=True)
    jetson.mkdir(parents=True)
    (base / "bladeRF-linux-mac80211.hwsim42").write_bytes((ROOT / "runtime/base/bladeRF-linux-mac80211.hwsim42").read_bytes())
    (jetson / "bladeRF-linux-mac80211.hwsim42").write_bytes((ROOT / "runtime/jetson/bladeRF-linux-mac80211.hwsim42").read_bytes())
    MODULE.verify_artifact_root(json.loads((ROOT / "manifest/baseline-manifest.json").read_text()), runtime, "runtime")
    with (base / "bladeRF-linux-mac80211.hwsim42").open("r+b") as handle:
        handle.write(b"X")
    try:
        MODULE.verify_artifact_root(json.loads((ROOT / "manifest/baseline-manifest.json").read_text()), runtime, "runtime")
    except ValueError as error:
        assert "runtime SHA-256 mismatch" in str(error)
    else:
        raise AssertionError("tampered bridge was accepted")
