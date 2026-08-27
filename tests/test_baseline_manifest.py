from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from jsonschema.validators import Draft202012Validator

from baseline_manifest import canonical_bytes, manifest_sha256, render_generated_config, validate_local_profile, validate_manifest


ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schema/baseline-manifest.schema.json").read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA)


def manifest():
    return json.loads((ROOT / "manifest/baseline-manifest.json").read_text(encoding="utf-8"))


def validate_schema(value):
    SCHEMA_VALIDATOR.validate(value)


def test_canonical_bytes_are_sorted_utf8_and_final_lf():
    assert canonical_bytes({"z": 1, "a": "한"}) == b'{"a":"\xed\x95\x9c","z":1}\n'


def test_canonical_digest_is_deterministic():
    assert manifest_sha256(manifest()) == manifest_sha256(dict(reversed(list(manifest().items()))))


def test_manifest_file_bytes_are_canonical():
    path = ROOT / "manifest/baseline-manifest.json"
    assert path.read_bytes() == canonical_bytes(manifest())


def test_manifest_v1_accepts_deferred_firmware_metadata():
    validate_manifest(manifest())
    validate_schema(manifest())


def test_manifest_accepts_exact_sealed_inventory_and_generated_config_shape():
    value = manifest()
    validate_manifest(value)
    validate_schema(value)


@pytest.mark.parametrize(("mutate", "schema_rejected"), [
    (lambda value: value.__setitem__("release", {"firmware_state": "invalid", "runtime_state": "deferred"}), True),
    (lambda value: value.__setitem__("release", {"firmware_state": "verified"}), True),
    (lambda value: value.__setitem__("provenance", {"build_metadata": "unknown", "extra": "reject"}), True),
    (lambda value: value["generated_configs"][0].__setitem__("repo_path", "/etc/passwd"), True),
    (lambda value: value["generated_configs"][0].__setitem__("repo_path", "generated\\base.env"), True),
    (lambda value: value["generated_configs"][0].__setitem__("repo_path", "generated/../base.env"), True),
    (lambda value: value["generated_configs"][0].__setitem__("generator_version", True), True),
    (lambda value: value["generated_configs"][0].__setitem__("generator_version", 0), True),
    (lambda value: value.__setitem__("generated_configs", value["generated_configs"][:-1]), True),
    (lambda value: value.__setitem__("artifacts", value["artifacts"][:-1]), True),
    (lambda value: value["artifacts"][0].__setitem__("sha256", "0" * 64), True),
    (lambda value: value["artifacts"][0]["source_metadata"].__setitem__("mode", "0755"), True),
    (lambda value: value["artifacts"][2].__setitem__("source_snapshot_path", "/var/tmp/mac80211_hwsim.ko"), True),
    (lambda value: value["artifacts"][0].__setitem__("build_metadata", "unknown"), True),
    (lambda value: value["artifacts"].append(deepcopy(value["artifacts"][0])), True),
])
def test_manifest_rejects_malformed_nested_structures(mutate, schema_rejected):
    value = deepcopy(manifest())
    mutate(value)
    with pytest.raises(ValueError):
        validate_manifest(value)
    if schema_rejected:
        with pytest.raises(ValidationError):
            validate_schema(value)


def test_manifest_accepts_verified_state_only_with_exact_approved_artifacts():
    value = manifest()
    value["release"] = {"firmware_state": "verified", "runtime_state": "verified"}
    validate_manifest(value)
    validate_schema(value)


def test_rendered_config_is_byte_identical_and_binds_manifest_digest():
    profile = {
        "node": "base",
        "serial": {"bladerf_serial": "EXAMPLE_BASE_SERIAL"},
        "network": {
            "ssid": "EXAMPLE_NOT_FOR_LIVE",
            "local_mac": "02:00:00:00:00:01",
            "management_if": "example-mgmt0",
            "peer_mac": "02:00:00:00:00:02",
            "rf_ip_cidr": "192.0.2.1/30",
            "peer_ip": "192.0.2.2",
        },
        "rf": {"frequency_mhz": 2412, "bandwidth_mhz": 20, "streams": 1},
    }
    rendered = render_generated_config(manifest(), profile, "base")
    assert rendered == render_generated_config(manifest(), profile, "base")
    assert manifest_sha256(manifest()).encode() in rendered
    assert rendered.startswith(b"BLADERF_GENERATOR_NAME=")
    assert b"BLADERF_NODE=base\n" in rendered
    assert rendered.endswith(b"\n")


def test_validate_local_profile_accepts_exact_base_and_jetson_shapes():
    base = json.loads((ROOT / "configs/local/base.local-profile.example.json").read_text(encoding="utf-8"))
    jetson = json.loads((ROOT / "configs/local/jetson.local-profile.example.json").read_text(encoding="utf-8"))
    validate_local_profile(base, "base")
    validate_local_profile(jetson, "jetson")


@pytest.mark.parametrize("profile", [
    {"node": "base", "serial": {}, "network": {}, "rf": {}},
    {
        "node": "base",
        "serial": {"bladerf_serial": "EXAMPLE_BASE_SERIAL", "extra": "reject"},
        "network": {"ssid": "EXAMPLE_NOT_FOR_LIVE", "local_mac": "02:00:00:00:00:01", "management_if": "example-mgmt0", "peer_mac": "02:00:00:00:00:02", "rf_ip_cidr": "192.0.2.1/30", "peer_ip": "192.0.2.2"},
        "rf": {"frequency_mhz": 2412, "bandwidth_mhz": 20, "streams": 1},
    },
    {
        "node": "jetson",
        "serial": {"bladerf_serial": "EXAMPLE_JETSON_SERIAL"},
        "network": {"ssid": "EXAMPLE_NOT_FOR_LIVE", "local_mac": "02:00:00:00:00:02", "peer_mac": "02:00:00:00:00:01", "rf_ip_cidr": "192.0.2.2/30", "peer_ip": "192.0.2.1"},
        "rf": {"frequency_mhz": 2412, "bandwidth_mhz": 20, "streams": 1},
    },
])
def test_validate_local_profile_rejects_non_exact_shapes(profile):
    with pytest.raises(ValueError):
        validate_local_profile(profile, profile["node"])


@pytest.mark.parametrize(("section", "key", "value"), [
    ("serial", "bladerf_serial", "bad;serial"),
    ("network", "ssid", "bad\nssid"),
    ("network", "ssid", 'bad"ssid'),
    ("network", "peer_mac", "02:00:00:00:00:01"),
    ("network", "peer_ip", "198.51.100.2"),
    ("network", "management_if", "bad/interface"),
    ("rf", "frequency_mhz", True),
])
def test_validate_local_profile_rejects_injection_and_inconsistent_peers(section, key, value):
    profile = json.loads((ROOT / "configs/local/base.local-profile.example.json").read_text(encoding="utf-8"))
    profile[section][key] = value
    with pytest.raises(ValueError):
        validate_local_profile(profile, "base")
