"""Canonical manifest-v1 serialization and structural validation."""

import base64
import ipaddress
import json
import re
from hashlib import sha256
from typing import Any, Set, Tuple


SCHEMA_ID = "https://bladerf-mesh.local/schema/baseline-manifest.schema.json"
TOP_LEVEL_KEYS = {"schema_id", "schema_version", "release", "artifacts", "generated_configs", "provenance"}
ARTIFACT_KEYS = {"node", "artifact_type", "repo_path", "sha256", "size_bytes", "source_snapshot_path", "source_metadata", "build_metadata", "distribution_authority"}
GENERATED_CONFIG_KEYS = {"node", "repo_path", "generator_name", "generator_version"}
EXPECTED_ARTIFACTS = {
    ("base", "rbf"): {
        "repo_path": "firmware/base/bladerf_wlan.rbf",
        "sha256": "cd82e18eb39a7b9832ece316e136a2de64c30cf16ffc53649051695cb215251c",
        "size_bytes": 12858972,
        "source_snapshot_path": "/sealed-snapshots/base/bladerf_wlan.rbf",
        "build_metadata": "unknown",
        "distribution_authority": "upstream open-source terms; see THIRD_PARTY_NOTICES.md",
        "source_metadata": {"file_type": "regular", "uid_gid": "0:0", "mode": "0444"},
    },
    ("jetson", "rbf"): {
        "repo_path": "firmware/jetson/bladerf_wlan.rbf",
        "sha256": "c8881ffa7423d98cdd85936322a8870f686d7a23451c68ce735f314c64d19191",
        "size_bytes": 12858972,
        "source_snapshot_path": "/sealed-snapshots/jetson/bladerf_wlan.rbf",
        "build_metadata": "unknown",
        "distribution_authority": "upstream open-source terms; see THIRD_PARTY_NOTICES.md",
        "source_metadata": {"file_type": "regular", "uid_gid": "0:0", "mode": "0444"},
    },
    ("jetson", "hwsim"): {
        "repo_path": "firmware/jetson/mac80211_hwsim.ko",
        "sha256": "dc08504f71ad995aed79ef7c77ce53836a78226a026ba905fa6c6eb0757ccb62",
        "size_bytes": 866976,
        "source_snapshot_path": "/sealed-snapshots/jetson/mac80211_hwsim.ko",
        "build_metadata": "vermagic=4.9.337-tegra SMP preempt mod_unload modversions aarch64",
        "distribution_authority": "GPL-2.0-only; see THIRD_PARTY_NOTICES.md",
        "source_metadata": {"file_type": "regular", "uid_gid": "0:0", "mode": "0444"},
    },
    ("base", "bridge"): {
        "repo_path": "runtime/base/bladeRF-linux-mac80211.hwsim42",
        "sha256": "a2d1be1adff8850b34d5d73dabebb39056419c52375f8e61dbe22d1d8139d5cb",
        "size_bytes": 194640,
        "source_snapshot_path": "/sealed-snapshots/base/bladeRF-linux-mac80211.hwsim42",
        "build_metadata": "ELF 64-bit LSB PIE x86-64; compiler=gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0",
        "distribution_authority": "GPL-2.0-or-later; see THIRD_PARTY_NOTICES.md",
        "source_metadata": {"file_type": "regular", "uid_gid": "1002:1002", "mode": "0775"},
    },
    ("jetson", "bridge"): {
        "repo_path": "runtime/jetson/bladeRF-linux-mac80211.hwsim42",
        "sha256": "398ee978ba6f28f861df4163a7aee1b1773e63002135611d7279296217cc77d5",
        "size_bytes": 262560,
        "source_snapshot_path": "/sealed-snapshots/jetson/bladeRF-linux-mac80211.hwsim42",
        "build_metadata": "unknown",
        "distribution_authority": "GPL-2.0-or-later; see THIRD_PARTY_NOTICES.md",
        "source_metadata": {"file_type": "regular", "uid_gid": "0:0", "mode": "0755"},
    },
}
EXPECTED_GENERATED_CONFIGS = {
    "base": {"repo_path": "generated/base.env", "generator_name": "baseline_manifest.render_generated_config", "generator_version": 1},
    "jetson": {"repo_path": "generated/jetson.env", "generator_name": "baseline_manifest.render_generated_config", "generator_version": 1},
}
MAC_PATTERN = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
SERIAL_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SSID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def manifest_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def validate_repository_relative_path(path: Any, label: str) -> str:
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or "\\" in path or ".." in path.split("/"):
        raise ValueError(f"{label} must be a safe repository-relative path")
    return path


def validate_manifest(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != TOP_LEVEL_KEYS:
        raise ValueError("manifest top-level keys are not exact")
    if value["schema_id"] != SCHEMA_ID or value["schema_version"] != 1:
        raise ValueError("unsupported manifest schema")
    release = value["release"]
    if (not isinstance(release, dict) or set(release) != {"firmware_state", "runtime_state"}
            or release["firmware_state"] not in {"deferred", "verified"}
            or release["runtime_state"] not in {"deferred", "verified"}):
        raise ValueError("release must contain only supported firmware and runtime states")
    provenance = value["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != {"build_metadata"} or not isinstance(provenance["build_metadata"], str):
        raise ValueError("provenance must contain only string build_metadata")
    if not isinstance(value["artifacts"], list) or not isinstance(value["generated_configs"], list):
        raise ValueError("artifacts and generated_configs must be lists")
    artifact_keys: Set[Tuple[str, str]] = set()
    for artifact in value["artifacts"]:
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_KEYS:
            raise ValueError("artifact keys are not exact")
        if artifact["node"] not in {"base", "jetson"} or artifact["artifact_type"] not in {"rbf", "hwsim", "bridge"}:
            raise ValueError("artifact node or type is unsupported")
        key = (artifact["node"], artifact["artifact_type"])
        if key in artifact_keys or key not in EXPECTED_ARTIFACTS:
            raise ValueError("artifact inventory is invalid")
        artifact_keys.add(key)
        expected = EXPECTED_ARTIFACTS[key]
        if any(artifact[field] != expected[field] for field in expected):
            raise ValueError("artifact does not match the sealed inventory")
        validate_repository_relative_path(artifact["repo_path"], "artifact repo_path")
        metadata = artifact["source_metadata"]
        if metadata != expected["source_metadata"]:
            raise ValueError("artifact source_metadata is invalid")
        if not isinstance(artifact["build_metadata"], str) or not artifact["build_metadata"] or not isinstance(artifact["distribution_authority"], str) or not artifact["distribution_authority"]:
            raise ValueError("artifact metadata values must be strings")
    if artifact_keys != set(EXPECTED_ARTIFACTS):
        raise ValueError("artifact inventory is incomplete")
    config_paths: Set[str] = set()
    config_nodes: Set[str] = set()
    for config in value["generated_configs"]:
        if not isinstance(config, dict) or set(config) != GENERATED_CONFIG_KEYS:
            raise ValueError("generated config keys are not exact")
        if config["node"] not in EXPECTED_GENERATED_CONFIGS or config["node"] in config_nodes or config["repo_path"] in config_paths:
            raise ValueError("generated config node or path is invalid")
        if any(config[field] != expected for field, expected in EXPECTED_GENERATED_CONFIGS[config["node"]].items()):
            raise ValueError("generated config does not match the sealed inventory")
        validate_repository_relative_path(config["repo_path"], "generated config repo_path")
        if not isinstance(config["generator_name"], str) or not config["generator_name"] or not isinstance(config["generator_version"], int) or isinstance(config["generator_version"], bool) or config["generator_version"] < 1:
            raise ValueError("generated config generator metadata is invalid")
        config_paths.add(config["repo_path"])
        config_nodes.add(config["node"])
    if config_nodes != set(EXPECTED_GENERATED_CONFIGS):
        raise ValueError("generated config inventory is incomplete")


def validate_local_profile(profile: Any, node: str) -> None:
    if node not in {"base", "jetson"}:
        raise ValueError("unsupported node")
    if not isinstance(profile, dict) or set(profile) != {"node", "serial", "network", "rf"}:
        raise ValueError("local profile keys are not exact")
    if profile["node"] != node:
        raise ValueError("profile node mismatch")
    if not all(isinstance(profile[key], dict) for key in ("serial", "network", "rf")):
        raise ValueError("profile sections must be objects")
    serial = profile["serial"]
    network = profile["network"]
    rf = profile["rf"]
    if (set(serial) != {"bladerf_serial"}
            or not isinstance(serial["bladerf_serial"], str)
            or not SERIAL_PATTERN.fullmatch(serial["bladerf_serial"])):
        raise ValueError("serial profile is invalid")
    required_network = {"ssid", "local_mac", "peer_mac", "rf_ip_cidr", "peer_ip"}
    if node == "base":
        required_network.add("management_if")
    if set(network) != required_network:
        raise ValueError("network profile is invalid")
    if not isinstance(network["ssid"], str) or not SSID_PATTERN.fullmatch(network["ssid"]):
        raise ValueError("ssid is invalid")
    for key in ("local_mac", "peer_mac"):
        value = network[key]
        if not isinstance(value, str) or not MAC_PATTERN.fullmatch(value):
            raise ValueError("mac address is invalid")
    if network["local_mac"] == network["peer_mac"]:
        raise ValueError("local and peer MAC addresses must differ")
    if node == "base" and (not isinstance(network["management_if"], str)
                           or not INTERFACE_PATTERN.fullmatch(network["management_if"])):
        raise ValueError("base management interface is invalid")
    try:
        local_interface = ipaddress.ip_interface(network["rf_ip_cidr"])
        peer_ip = ipaddress.ip_address(network["peer_ip"])
    except ValueError as exc:
        raise ValueError("IP profile is invalid") from exc
    if (local_interface.version != 4 or peer_ip.version != 4
            or local_interface.ip == peer_ip or peer_ip not in local_interface.network):
        raise ValueError("local and peer IP addresses must be distinct IPv4 peers")
    required_rf = {"frequency_mhz", "bandwidth_mhz", "streams"}
    if node == "jetson":
        required_rf = required_rf | {"dsa_gain_db"}
    if set(rf) != required_rf:
        raise ValueError("rf profile keys are invalid")
    for key in ("frequency_mhz", "bandwidth_mhz", "streams"):
        value = rf[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("rf numeric values are invalid")
    if node == "jetson":
        gain = rf["dsa_gain_db"]
        if not isinstance(gain, int) or isinstance(gain, bool) or gain < -30 or gain > 30:
            raise ValueError("jetson dsa_gain_db is invalid")


def render_generated_config(manifest: Any, profile: Any, node: str) -> bytes:
    validate_manifest(manifest)
    validate_local_profile(profile, node)
    encoded = {}
    for section in ("serial", "network", "rf"):
        encoded[section] = base64.b64encode(canonical_bytes(profile[section]).rstrip(b"\n")).decode("ascii")
    lines = (
        "BLADERF_GENERATOR_NAME=baseline_manifest.render_generated_config",
        "BLADERF_GENERATOR_VERSION=1",
        "BLADERF_MANIFEST_SHA256=" + manifest_sha256(manifest),
        "BLADERF_NETWORK_B64=" + encoded["network"],
        "BLADERF_NODE=" + node,
        "BLADERF_RF_B64=" + encoded["rf"],
        "BLADERF_SERIAL_B64=" + encoded["serial"],
    )
    return ("\n".join(lines) + "\n").encode("ascii")
