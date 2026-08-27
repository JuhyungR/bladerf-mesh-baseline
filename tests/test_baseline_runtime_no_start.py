from pathlib import Path
import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
import types
import pytest


ROOT = Path(__file__).parents[1]
NODE = ROOT / "tools" / "bladerf-link-node"
ADMIN = ROOT / "tools" / "bladerf-project-admin"
INSTALLER = ROOT / "tools" / "install-baseline-runtime"


def run(command: str):
    return subprocess.run(["bash", "-lc", command], text=True, capture_output=True, check=False, cwd=ROOT)


def bash_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if len(value) >= 3 and value[1:3] == ":/":
        return "/mnt/" + value[0].lower() + value[2:]
    return value


def load_node_namespace():
    previous_fcntl = sys.modules.get("fcntl")
    sys.modules["fcntl"] = types.ModuleType("fcntl")
    try:
        return runpy.run_path(str(NODE))
    finally:
        if previous_fcntl is None:
            del sys.modules["fcntl"]
        else:
            sys.modules["fcntl"] = previous_fcntl


def test_runtime_uses_bounded_node_specific_readiness_windows(tmp_path):
    namespace = load_node_namespace()
    assert namespace["JETSON_READY_STEPS"] == 50
    assert namespace["BASE_ASSOCIATION_READY_STEPS"] == 1200
    source = NODE.read_text(encoding="utf-8")
    assert "ready_limit = JETSON_READY_STEPS" in source
    assert "ready_limit = BASE_ASSOCIATION_READY_STEPS" in source

    runtime = namespace["Runtime"].__new__(namespace["Runtime"])
    runtime.role = namespace["FakeProcess"]()
    pauses = []
    runtime.pause = pauses.append
    log_path = tmp_path / "not-ready.log"
    with log_path.open("x+") as role_log:
        for limit in (namespace["JETSON_READY_STEPS"], namespace["BASE_ASSOCIATION_READY_STEPS"]):
            pauses.clear()
            with pytest.raises(SystemExit) as timeout:
                runtime.wait_for_role_ready(role_log, "READY", limit)
            assert timeout.value.code == 1
            assert pauses == [0.1] * limit

        runtime.role.returncode = 1
        pauses.clear()
        with pytest.raises(SystemExit) as child_exit:
            runtime.wait_for_role_ready(role_log, "READY", namespace["BASE_ASSOCIATION_READY_STEPS"])
        assert child_exit.value.code == 1
        assert pauses == []


def install_test_root(node: str, tmp_path: Path, suffix: str):
    test_root = "/tmp/bladerf-baseline-%d-%s-%s" % (os.getpid(), node, suffix)
    receipt = tmp_path / (node + "-" + suffix + ".json")
    profile = ROOT / "configs" / "local" / (node + ".local-profile.example.json")
    common = (
        "--node " + node
        + " --manifest manifest/baseline-manifest.json"
        + " --profile " + shlex.quote(bash_path(profile))
        + " --root " + shlex.quote(test_root)
        + " --receipt " + shlex.quote(bash_path(receipt))
    )
    result = run(
        "rm -rf -- " + shlex.quote(test_root) + "; "
        + "./tools/install-baseline-runtime " + common
    )
    assert result.returncode == 0, result.stderr
    return test_root, receipt


def test_runner_status_is_canonical_and_run_is_no_start_blocked():
    status = run("./tools/bladerf-link-node status base")
    assert status.returncode == 0
    assert status.stdout == (
        "inventory_version=g148-immutable-runtime-v1\n"
        "node=base\n"
        "runtime_state=C_BYTES_VALID\n"
        "start_authority=NO_START\n"
        "active=inactive\n"
        "sub=dead\n"
        "main_pid=0\n"
        "n_restarts=0\n"
        "wlan0=0\n"
        "hwsim=absent\n"
    )
    denied = run("./tools/bladerf-link-node run base")
    assert denied.returncode == 77 and "NO_START" in denied.stderr


def test_installed_status_permission_boundary_fails_closed(monkeypatch, capsys):
    namespace = load_node_namespace()
    monkeypatch.setattr(
        namespace["os"].path, "lexists",
        lambda path: path == "/etc/bladerf-link",
    )
    monkeypatch.setattr(namespace["os"].path, "islink", lambda _path: False)
    monkeypatch.setattr(namespace["os"].path, "isfile", lambda _path: False)

    assert namespace["installed_context"]("status") is True
    with pytest.raises(SystemExit) as rejected:
        namespace["read_authority"]("status")
    assert rejected.value.code == 78
    assert "installed authority is invalid" in capsys.readouterr().err


def test_installed_status_collects_live_state_from_boundary(monkeypatch, capsys):
    namespace = load_node_namespace()
    monkeypatch.setattr(
        namespace["os"].path, "lexists",
        lambda path: path == "/etc/bladerf-link",
    )
    monkeypatch.setattr(
        namespace["os"].path, "isdir",
        lambda path: path == "/sys/module/mac80211_hwsim",
    )
    monkeypatch.setattr(
        namespace["subprocess"], "check_output",
        lambda _argv: b"ActiveState=active\nSubState=running\nMainPID=123\nNRestarts=0\n",
    )
    monkeypatch.setattr(namespace["subprocess"], "call", lambda *_args, **_kwargs: 0)

    namespace["status"]("base", "EXECUTION_RESERVED")
    assert capsys.readouterr().out == (
        "inventory_version=g148-immutable-runtime-v1\n"
        "node=base\n"
        "runtime_state=C_BYTES_VALID\n"
        "start_authority=EXECUTION_RESERVED\n"
        "active=active\n"
        "sub=running\n"
        "main_pid=123\n"
        "n_restarts=0\n"
        "wlan0=1\n"
        "hwsim=present\n"
    )


def test_base_management_snapshot_ignores_dhcp_lifetimes_but_not_address_changes():
    snapshot = load_node_namespace()["stable_management_snapshot"]
    first = [{
        "ifname": "example-mgmt0", "address": "02:00:00:00:00:84", "operstate": "UP",
        "addr_info": [{"family": "inet", "local": "192.0.2.84", "prefixlen": 24,
                       "scope": "global", "label": "example-mgmt0", "valid_life_time": 4500,
                       "preferred_life_time": 4500}],
    }]
    second = json.loads(json.dumps(first))
    second[0]["addr_info"][0]["valid_life_time"] = 4495
    second[0]["addr_info"][0]["preferred_life_time"] = 4495
    assert snapshot(json.dumps(first)) == snapshot(json.dumps(second))
    second[0]["addr_info"][0]["local"] = "192.0.2.85"
    assert snapshot(json.dumps(first)) != snapshot(json.dumps(second))


def test_production_rf_boundary_is_fixed_while_local_values_remain_profile_owned():
    validate = load_node_namespace()["validate_fixed_profile"]
    profiles = {
        "base": json.loads((ROOT / "configs/local/base.local-profile.example.json").read_text(encoding="utf-8")),
        "jetson": json.loads((ROOT / "configs/local/jetson.local-profile.example.json").read_text(encoding="utf-8")),
    }
    validate(profiles["base"], "base")
    validate(profiles["jetson"], "jetson")
    drifted = json.loads(json.dumps(profiles["base"]))
    drifted["rf"]["frequency_mhz"] = 2450
    try:
        validate(drifted, "base")
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("fixed profile drift was accepted")


def test_units_keep_exact_runner_execstart_and_do_not_restart():
    assert "ExecStart=/usr/local/libexec/bladerf-link-node base /etc/bladerf-link/base.env" in (ROOT / "systemd/bladerf-link-base.service").read_text()
    assert "ExecStart=/usr/local/libexec/bladerf-link-node jetson /etc/bladerf-link/jetson.env" in (ROOT / "systemd/bladerf-link-jetson.service").read_text()
    assert "Restart=no" in (ROOT / "systemd/bladerf-link-base.service").read_text()


def test_profile_free_manifest_verifier_and_admin_status():
    assert run("./tools/install-baseline-runtime --verify-manifest-only --manifest manifest/baseline-manifest.json").returncode == 0
    assert run("./tools/bladerf-project-admin status jetson").returncode == 0


def test_admin_manifest_verification_resolves_module_from_installed_layout(tmp_path):
    prefix = tmp_path / "prefix"
    admin = prefix / "sbin" / "bladerf-project-admin"
    module = prefix / "lib" / "bladerf-link" / "baseline_manifest.py"
    admin.parent.mkdir(parents=True)
    module.parent.mkdir(parents=True)
    shutil.copy2(ADMIN, admin)
    shutil.copy2(ROOT / "baseline_manifest.py", module)
    manifest = tmp_path / "baseline-manifest.json"
    shutil.copy2(ROOT / "manifest/baseline-manifest.json", manifest)
    admin.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        ["bash", "prefix/sbin/bladerf-project-admin", "--verify-manifest", "baseline-manifest.json"],
        text=True, capture_output=True, check=False, cwd=tmp_path, env=environment,
    )
    assert result.returncode == 0, result.stderr


def test_disposable_test_root_install_and_verify_are_no_start(tmp_path):
    for node in ("base", "jetson"):
        test_root = "/tmp/bladerf-baseline-%d-%s" % (os.getpid(), node)
        install_receipt = tmp_path / (node + "-install.json")
        verify_receipt = tmp_path / (node + "-verify.json")
        profile = ROOT / "configs" / "local" / (node + ".local-profile.example.json")
        common = (
            "--node " + node
            + " --manifest manifest/baseline-manifest.json"
            + " --profile " + shlex.quote(bash_path(profile))
            + " --root " + shlex.quote(test_root)
        )
        result = run(
            "rm -rf -- " + shlex.quote(test_root) + "; "
            + "./tools/install-baseline-runtime " + common
            + " --receipt " + shlex.quote(bash_path(install_receipt)) + "; "
            + "./tools/install-baseline-runtime --verify-only " + common
            + " --receipt " + shlex.quote(bash_path(verify_receipt)) + "; "
            + "test ! -e " + shlex.quote(test_root + "/etc/sudoers.d") + "; "
            + "test \"$(cat " + shlex.quote(test_root + "/etc/bladerf-link/start-authority") + ")\" = NO_START; "
            + "grep -q '^BLADERF_MANIFEST_SHA256=' " + shlex.quote(test_root + "/etc/bladerf-link/" + node + ".env") + "; "
            + "BLADERF_ROOT=" + shlex.quote(test_root) + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
            + " " + node + " /etc/bladerf-link/" + node + ".env >/dev/null 2>&1; test $? -eq 77; "
            + "rm -rf -- " + shlex.quote(test_root)
        )
        assert result.returncode == 0, result.stderr
        assert "install_status=install" in result.stdout
        assert "install_status=verify" in result.stdout
        for receipt_path, operation in ((install_receipt, "install"), (verify_receipt, "verify")):
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            assert receipt["status"] == "pass" and receipt["operation"] == operation
            assert receipt["node"] == node and receipt["profile_schema_valid"] is True
            assert receipt["runtime_state"] == "verified"
            assert receipt["run_id"] == tmp_path.name
            assert receipt["c_bytes_state"] == "C_BYTES_VALID" and receipt["start_policy"] == "NO_START" and receipt["stopped_clean"] is True
            assert receipt["unit"] == {"active_state": "inactive", "main_pid": 0, "nrestarts": 0, "sub_state": "dead", "unit_file_state": "static"}
            assert receipt["authority"]["start_policy"] == "NO_START"
            assert all(receipt["authority"][key] is False for key in ("project_sudoers_installed", "start_vector_installed", "restart_vector_installed", "systemctl_vector_installed", "shell_vector_installed"))
            assert receipt["installer_rf_started"] is False and receipt["rf_started"] is False
            assert receipt["production_mutation"] is False and receipt["test_root"] is True
            bridge = next(item for item in receipt["artifacts"] if item["artifact_type"] == "bridge")
            assert bridge["mode"] == "0555"
            assert bridge["installed_path"] == "/usr/local/lib/bladerf-link/runtime/%s/bladeRF-linux-mac80211.hwsim42" % node


def test_admin_can_reserve_and_revoke_execution_in_test_root(tmp_path):
    test_root, _receipt = install_test_root("jetson", tmp_path, "promote")
    promoted = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution jetson"
    )
    assert promoted.returncode == 0, promoted.stderr
    status = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " status jetson"
    )
    assert "start_authority=EXECUTION_RESERVED" in status.stdout
    assert "hwsim=absent" in status.stdout
    repeated = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution jetson"
    )
    assert repeated.returncode == 78
    revoked = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " revoke-execution jetson"
    )
    assert revoked.returncode == 0, revoked.stderr
    status = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " status jetson"
    )
    assert "start_authority=NO_START" in status.stdout
    repeated = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " revoke-execution jetson"
    )
    assert repeated.returncode == 78
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_authority_mutation_requires_an_explicit_non_root_test_root():
    rejected = run("./tools/bladerf-project-admin reserve-execution base")
    assert rejected.returncode == 78


def test_production_promotion_is_root_only_and_stopped_clean_guarded():
    source = ADMIN.read_text(encoding="utf-8")
    for required in (
        "production authority mutation requires root on the real filesystem",
        "UnitFileState=static", "ActiveState=inactive", "SubState=dead",
        "MainPID=0", "NRestarts=0", "runtime_state=C_BYTES_VALID",
        "wlan0=0", "hwsim=absent", "promote-execution|remove-start-promotion",
        "production runtime residue is present",
        "production NetworkManager guard residue is present",
    ):
        assert required in source
    validation = source.index('require_production_stopped "$2"')
    mutation = source.index('mutate_authority "" "$AUTHORITY_NO_START" "$AUTHORITY_RESERVED"')
    assert validation < mutation


def test_no_start_is_checked_before_generated_config_or_payload(tmp_path):
    test_root, _receipt = install_test_root("base", tmp_path, "authority-first")
    config = test_root + "/etc/bladerf-link/base.env"
    result = run(
        "printf 'malformed-config\\n' > " + shlex.quote(config) + "; "
        + "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
        + " base /etc/bladerf-link/base.env"
    )
    assert result.returncode == 77
    assert "NO_START" in result.stderr
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_promoted_dry_run_records_minimal_base_and_jetson_lifecycles(tmp_path):
    expectations = {
        "base": ["STARTING", "LOAD_RBF", "LOAD_HWSIM_MODPROBE", "IFACE_READY", "BRIDGE_START", "STA_START", "KEEPALIVE_START", "CLEANUP_OK"],
        "jetson": ["STARTING", "LOAD_RBF", "LOAD_HWSIM_INSMOD", "IFACE_READY", "BRIDGE_START", "AP_START", "CLEANUP_OK"],
    }
    for node, markers in expectations.items():
        test_root, _receipt = install_test_root(node, tmp_path, "dry-run")
        state_dir = test_root + "/test-state"
        assert run("mkdir -m 700 -- " + shlex.quote(state_dir)).returncode == 0
        promote = run(
            "BLADERF_ROOT=" + shlex.quote(test_root) + " "
            + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution " + node
        )
        assert promote.returncode == 0, promote.stderr
        live_blocked = run(
            "BLADERF_ROOT=" + shlex.quote(test_root)
            + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
            + " " + node + " /etc/bladerf-link/" + node + ".env"
        )
        assert live_blocked.returncode == 78
        assert "actual runtime requires the real root filesystem" in live_blocked.stderr
        command = (
            "BLADERF_ROOT=" + shlex.quote(test_root)
            + " BLADERF_TEST_MODE=1"
            + " BLADERF_LINK_STATE_DIR=" + shlex.quote(state_dir)
            + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
            + " " + node + " /etc/bladerf-link/" + node + ".env"
        )
        result = run(command)
        assert result.returncode == 0, result.stderr
        timeline = run("cat -- " + shlex.quote(state_dir + "/" + node + ".timeline"))
        assert timeline.returncode == 0
        assert timeline.stdout.splitlines() == markers
        assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_fake_backend_runs_real_lifecycle_and_cleanup_without_side_effects(tmp_path):
    for node in ("base", "jetson"):
        test_root, _receipt = install_test_root(node, tmp_path, "fake-" + node)
        state_dir = test_root + "/fake-state"
        trace_dir = test_root + "/test-output"
        trace = trace_dir + "/" + node + ".jsonl"
        assert run("mkdir -m 700 -- " + shlex.quote(trace_dir)).returncode == 0
        reserve = run(
            "BLADERF_ROOT=" + shlex.quote(test_root) + " "
            + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution " + node
        )
        assert reserve.returncode == 0, reserve.stderr
        result = run(
            "BLADERF_ROOT=" + shlex.quote(test_root)
            + " BLADERF_TEST_MODE=2 BLADERF_LINK_STATE_DIR=" + shlex.quote(state_dir)
            + " BLADERF_TEST_TRACE=" + shlex.quote(trace)
            + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
            + " " + node + " /etc/bladerf-link/" + node + ".env"
        )
        assert result.returncode == 0, result.stderr
        observed = run("cat -- " + shlex.quote(trace))
        entries = [json.loads(line) for line in observed.stdout.splitlines()]
        commands = [entry["argv"] for entry in entries]
        serial = "EXAMPLE_BASE_SERIAL" if node == "base" else "EXAMPLE_JETSON_SERIAL"
        rbf = test_root + "/usr/local/lib/bladerf-link/firmware/" + node + "/bladerf_wlan.rbf"
        bridge = test_root + "/usr/local/lib/bladerf-link/runtime/" + node + "/bladeRF-linux-mac80211.hwsim42"
        prefix = [["ip", "link", "show", "dev", "wlan0"], ["bladeRF-cli", "-p"], ["iw", "dev"]]
        cidr = "192.0.2.1/30" if node == "base" else "192.0.2.2/30"
        peer_ip = "192.0.2.2" if node == "base" else "192.0.2.1"
        bridge_command = [bridge, "-f", "2412", "-g", "0", "-V"]
        if node == "base":
            bridge_command.append("-H")
        common_tail = [
            ["ip", "link", "set", "wlan0", "down"],
            ["ip", "link", "set", "wlan0", "address", "02:00:00:00:00:01" if node == "base" else "02:00:00:00:00:02"],
            ["ip", "link", "set", "wlan0", "up"],
            ["ip", "address", "add", cidr, "dev", "wlan0"],
            ["ip", "route", "replace", peer_ip, "dev", "wlan0"],
            bridge_command, ["1"],
        ]
        if node == "base":
            expected = prefix + [
                ["ip", "-j", "address", "show", "dev", "example-mgmt0"], ["example-mgmt0"],
                ["bladeRF-cli", "-d", "*:serial=" + serial, "-l", rbf],
                ["modprobe", "mac80211_hwsim", "radios=1", "support_p2p_device=0"], ["iw", "dev"],
                ["nmcli", "-g", "GENERAL.STATE", "device", "show", "wlan0"],
            ] + common_tail + [
                ["wpa_supplicant", "-dd", "-t", "-Dnl80211", "-i", "wlan0", "-c", state_dir + "/base-wpa.conf"],
                ["ping", "-n", "-I", "wlan0", "-i", "5", peer_ip], ["0.1"],
                ["ip", "route", "del", peer_ip, "dev", "wlan0"],
                ["ip", "address", "del", cidr, "dev", "wlan0"],
                ["ip", "link", "set", "wlan0", "down"], ["rmmod", "mac80211_hwsim"],
                ["ip", "-j", "address", "show", "dev", "example-mgmt0"], ["example-mgmt0"],
            ]
        else:
            expected = prefix + [
                ["bladeRF-cli", "-d", "*:serial=" + serial, "-l", rbf],
                ["systemctl", "is-active", "--quiet", "wpa_supplicant.service"],
                ["systemctl", "stop", "wpa_supplicant.service"], ["modprobe", "cfg80211"], ["modprobe", "mac80211"],
                ["insmod", test_root + "/usr/local/lib/bladerf-link/firmware/jetson/mac80211_hwsim.ko", "radios=1", "support_p2p_device=0"],
                ["iw", "dev"], ["nmcli", "device", "set", "wlan0", "managed", "no"],
            ] + common_tail + [
                ["hostapd", "-dd", state_dir + "/jetson-hostapd.conf"],
                ["ip", "route", "del", peer_ip, "dev", "wlan0"],
                ["ip", "address", "del", cidr, "dev", "wlan0"],
                ["ip", "link", "set", "wlan0", "down"], ["rmmod", "mac80211_hwsim"],
                ["systemctl", "start", "wpa_supplicant.service"],
            ]
        assert commands == expected
        assert commands.count(["ip", "address", "add", cidr, "dev", "wlan0"]) == 1
        assert commands.count(["ip", "address", "del", cidr, "dev", "wlan0"]) == 1
        assert commands.count(["ip", "route", "replace", peer_ip, "dev", "wlan0"]) == 1
        assert commands.count(["ip", "route", "del", peer_ip, "dev", "wlan0"]) == 1
        assert run("test ! -e " + shlex.quote(state_dir)).returncode == 0
        assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_base_keepalive_launch_failure_is_fail_closed_and_cleaned(tmp_path):
    test_root, _receipt = install_test_root("base", tmp_path, "keepalive-failure")
    state_dir = test_root + "/fake-state"
    trace_dir = test_root + "/test-output"
    trace = trace_dir + "/base-keepalive-failure.jsonl"
    assert run("mkdir -m 700 -- " + shlex.quote(trace_dir)).returncode == 0
    assert run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution base"
    ).returncode == 0
    result = run(
        "BLADERF_ROOT=" + shlex.quote(test_root)
        + " BLADERF_TEST_MODE=2 BLADERF_TEST_FAIL_AT=ping"
        + " BLADERF_LINK_STATE_DIR=" + shlex.quote(state_dir)
        + " BLADERF_TEST_TRACE=" + shlex.quote(trace)
        + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
        + " base /etc/bladerf-link/base.env"
    )
    assert result.returncode != 0
    commands = [json.loads(line)["argv"] for line in run("cat -- " + shlex.quote(trace)).stdout.splitlines()]
    assert ["ping", "-n", "-I", "wlan0", "-i", "5", "192.0.2.2"] in commands
    status = run("cat -- " + shlex.quote(state_dir + "/base.status"))
    assert "state=FAILED" in status.stdout and "cleanup_complete=false" in status.stdout
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_cleanup_stops_keepalive_before_role_and_bridge(tmp_path):
    namespace = load_node_namespace()
    runtime = namespace["Runtime"].__new__(namespace["Runtime"])
    runtime.cleaning = False
    runtime.incident = False
    runtime.state = str(tmp_path / "runtime-state")
    Path(runtime.state).mkdir()
    runtime.keepalive = object()
    runtime.role = object()
    runtime.bridge = object()
    runtime.logs = []
    runtime.route_owned = False
    runtime.ip_owned = False
    runtime.interface = None
    runtime.hwsim_owned = False
    runtime.wpa_stopped = False
    runtime.guard_owned = False
    runtime.fake = True
    runtime.module_present = lambda: False
    runtime.write_status = lambda _state, _clean=False: None
    stopped = []
    runtime.stop_child = stopped.append

    assert runtime.cleanup() is True
    assert stopped == [runtime.keepalive, runtime.role, runtime.bridge]


def test_fake_backend_failure_runs_jetson_cleanup_and_preserves_failure_state(tmp_path):
    test_root, _receipt = install_test_root("jetson", tmp_path, "fake-failure")
    state_dir = test_root + "/fake-state"
    trace_dir = test_root + "/test-output"
    trace = trace_dir + "/jetson-failure.jsonl"
    assert run("mkdir -m 700 -- " + shlex.quote(trace_dir)).returncode == 0
    reserve = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution jetson"
    )
    assert reserve.returncode == 0, reserve.stderr
    result = run(
        "BLADERF_ROOT=" + shlex.quote(test_root)
        + " BLADERF_TEST_MODE=2 BLADERF_TEST_FAIL_AT=hostapd"
        + " BLADERF_LINK_STATE_DIR=" + shlex.quote(state_dir)
        + " BLADERF_TEST_TRACE=" + shlex.quote(trace)
        + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
        + " jetson /etc/bladerf-link/jetson.env"
    )
    assert result.returncode != 0
    observed = run("cat -- " + shlex.quote(trace))
    commands = [json.loads(line)["argv"] for line in observed.stdout.splitlines()]
    assert ["rmmod", "mac80211_hwsim"] in commands
    assert ["systemctl", "start", "wpa_supplicant.service"] in commands
    status = run("cat -- " + shlex.quote(state_dir + "/jetson.status"))
    assert "state=FAILED" in status.stdout and "cleanup_complete=false" in status.stdout
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_fake_backend_cleanup_failure_is_nonzero_and_preserves_evidence(tmp_path):
    test_root, _receipt = install_test_root("base", tmp_path, "fake-cleanup-failure")
    state_dir = test_root + "/fake-state"
    trace_dir = test_root + "/test-output"
    trace = trace_dir + "/base-rmmod-failure.jsonl"
    assert run("mkdir -m 700 -- " + shlex.quote(trace_dir)).returncode == 0
    assert run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution base"
    ).returncode == 0
    result = run(
        "BLADERF_ROOT=" + shlex.quote(test_root)
        + " BLADERF_TEST_MODE=2 BLADERF_TEST_FAIL_AT=rmmod"
        + " BLADERF_LINK_STATE_DIR=" + shlex.quote(state_dir)
        + " BLADERF_TEST_TRACE=" + shlex.quote(trace)
        + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
        + " base /etc/bladerf-link/base.env"
    )
    assert result.returncode != 0 and "cleanup failed" in result.stderr
    status = run("cat -- " + shlex.quote(state_dir + "/base.status"))
    assert "state=FAILED" in status.stdout and "cleanup_complete=false" in status.stdout
    assert run("test -s " + shlex.quote(trace)).returncode == 0
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_test_modes_reject_paths_outside_the_disposable_root(tmp_path):
    test_root, _receipt = install_test_root("base", tmp_path, "test-containment")
    outside = test_root + "-outside"
    assert run("mkdir -m 700 -- " + shlex.quote(outside)).returncode == 0
    assert run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution base"
    ).returncode == 0
    rejected = run(
        "BLADERF_ROOT=" + shlex.quote(test_root)
        + " BLADERF_TEST_MODE=1 BLADERF_LINK_STATE_DIR=" + shlex.quote(outside)
        + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
        + " base /etc/bladerf-link/base.env"
    )
    assert rejected.returncode == 78 and "escapes BLADERF_ROOT" in rejected.stderr
    assert run("test ! -e " + shlex.quote(outside + "/base.timeline")).returncode == 0
    assert run("rm -rf -- " + shlex.quote(test_root) + " " + shlex.quote(outside)).returncode == 0


def test_test_mode_root_guard_precedes_authority_config_and_module_reads():
    rejected = run(
        "BLADERF_ROOT=/ BLADERF_TEST_MODE=1 BLADERF_LINK_STATE_DIR=/tmp "
        + "./tools/bladerf-link-node base /etc/bladerf-link/base.env"
    )
    assert rejected.returncode == 78 and "explicit non-root BLADERF_ROOT" in rejected.stderr
    source = NODE.read_text(encoding="utf-8")
    main_source = source[source.index("def main():"):]
    assert main_source.index("validate_disposable_test_root()") < main_source.index("authority = read_authority(command)")


def test_reserved_runner_rejects_tampered_manifest_bound_payload(tmp_path):
    test_root, _receipt = install_test_root("base", tmp_path, "reserved-tamper")
    state_dir = test_root + "/tampered-state"
    assert run("mkdir -m 700 -- " + shlex.quote(state_dir)).returncode == 0
    reserve = run(
        "BLADERF_ROOT=" + shlex.quote(test_root) + " "
        + shlex.quote(test_root + "/usr/local/sbin/bladerf-project-admin") + " reserve-execution base"
    )
    assert reserve.returncode == 0, reserve.stderr
    bridge = test_root + "/usr/local/lib/bladerf-link/runtime/base/bladeRF-linux-mac80211.hwsim42"
    result = run(
        "chmod u+w " + shlex.quote(bridge) + "; printf X | dd of=" + shlex.quote(bridge)
        + " bs=1 seek=0 conv=notrunc status=none; chmod 0555 " + shlex.quote(bridge) + "; "
        + "BLADERF_ROOT=" + shlex.quote(test_root)
        + " BLADERF_TEST_MODE=1 BLADERF_LINK_STATE_DIR=" + shlex.quote(state_dir)
        + " " + shlex.quote(test_root + "/usr/local/libexec/bladerf-link-node")
        + " base /etc/bladerf-link/base.env"
    )
    assert result.returncode != 0
    assert "digest differs" in result.stderr
    assert run("test ! -e " + shlex.quote(state_dir + "/base.timeline")).returncode == 0
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_installer_has_no_rf_or_service_start_command():
    source = INSTALLER.read_text(encoding="utf-8")
    for forbidden in ("systemctl start", "systemctl restart", "systemctl enable", 'modprobe "', "ip link", "iw dev", "bladeRF-cli -"):
        assert forbidden not in source
    assert "required_commands=(python3 systemctl ip iw bladeRF-cli modprobe rmmod)" in source
    assert "required_commands+=(nmcli wpa_supplicant ping)" in source
    assert "required_commands+=(hostapd insmod)" in source
    assert '[[ $os_version == 24.04 && $architecture == x86_64 && $kernel == 6.8.0-136-generic ]]' in source


def test_actual_runner_is_single_attempt_and_excludes_acceptance_side_work():
    source = NODE.read_text(encoding="utf-8")
    for required in (
        '["bladeRF-cli", "-d"', '["modprobe", "mac80211_hwsim"',
        '["insmod", rooted("/usr/local/lib/bladerf-link/firmware/jetson/mac80211_hwsim.ko")',
        '["hostapd", "-dd"', '["wpa_supplicant", "-dd", "-t", "-Dnl80211"',
        '["ping", "-n", "-I", self.interface, "-i", "5", self.network["peer_ip"]]',
        '["rmmod", "mac80211_hwsim"]', 'fcntl.LOCK_NB',
        'for process in (self.keepalive, self.role, self.bridge):',
        'shutil.rmtree(self.state)',
    ):
        assert required in source
    for forbidden in ("iperf", "tcpdump", "tshark", "throughput", "capture", "retry"):
        assert forbidden not in source.lower()
    assert '["ip", "address", "add", self.network["rf_ip_cidr"], "dev", self.interface]' in source
    assert '["ip", "address", "del", self.network["rf_ip_cidr"], "dev", self.interface]' in source
    assert '["ip", "route", "replace", self.network["peer_ip"], "dev", self.interface]' in source
    assert '["ip", "route", "del", self.network["peer_ip"], "dev", self.interface]' in source


def test_installed_manifest_module_remains_python36_compatible():
    source = (ROOT / "baseline_manifest.py").read_text(encoding="utf-8")
    for unsupported in ("set[", "list[", "dict[", "tuple[", "datetime.UTC", "monotonic_ns"):
        assert unsupported not in source


def test_executable_and_payload_line_endings_are_repository_pinned():
    attributes = (ROOT / ".gitattributes").read_text(encoding="ascii")
    assert "tools/* text eol=lf" in attributes
    assert "*.py text eol=lf" in attributes
    assert "*.rbf binary" in attributes and "runtime/*/* binary" in attributes


def test_operator_tools_are_executable_in_a_fresh_clone():
    expected = {
        "tools/bladerf-link-node",
        "tools/bladerf-project-admin",
        "tools/install-baseline-runtime",
        "tools/build-baseline-release.py",
    }
    result = subprocess.run(
        ["git", "ls-files", "-s", "--"] + sorted(expected),
        text=True, capture_output=True, check=False, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    observed = {line.split(maxsplit=3)[3]: line.split(maxsplit=1)[0] for line in result.stdout.splitlines()}
    assert observed == {path: "100755" for path in expected}


def test_installer_uses_an_absolute_artifact_root_for_production_verification():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "artifact_root=${root:-/}" in source
    assert source.count('"$artifact_root"') == 2
    assert "is_test_root=false" in source and "[[ -z $root ]] || is_test_root=true" in source
    assert '"test_root": is_test_root == "true"' in source


def test_verify_fails_closed_before_receipt_when_installed_firmware_changes(tmp_path):
    test_root = "/tmp/bladerf-baseline-%d-tamper" % os.getpid()
    install_receipt = tmp_path / "tamper-install.json"
    failed_receipt = tmp_path / "tamper-verify.json"
    profile = bash_path(ROOT / "configs" / "local" / "base.local-profile.example.json")
    common = (
        "--node base --manifest manifest/baseline-manifest.json"
        + " --profile " + shlex.quote(profile)
        + " --root " + shlex.quote(test_root)
    )
    result = run(
        "set -e; rm -rf -- " + shlex.quote(test_root) + "; "
        + "./tools/install-baseline-runtime " + common + " --receipt " + shlex.quote(bash_path(install_receipt)) + "; "
        + "chmod u+w " + shlex.quote(test_root + "/usr/local/lib/bladerf-link/firmware/base/bladerf_wlan.rbf") + "; "
        + "printf X | dd of=" + shlex.quote(test_root + "/usr/local/lib/bladerf-link/firmware/base/bladerf_wlan.rbf") + " bs=1 seek=0 conv=notrunc status=none; "
        + "./tools/install-baseline-runtime --verify-only " + common + " --receipt " + shlex.quote(bash_path(failed_receipt))
    )
    assert result.returncode != 0
    assert "digest differs" in result.stderr
    assert not failed_receipt.exists()
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_verify_fails_closed_before_receipt_when_installed_bridge_changes(tmp_path):
    test_root = "/tmp/bladerf-baseline-%d-bridge-tamper" % os.getpid()
    install_receipt = tmp_path / "bridge-tamper-install.json"
    failed_receipt = tmp_path / "bridge-tamper-verify.json"
    profile = bash_path(ROOT / "configs" / "local" / "base.local-profile.example.json")
    common = (
        "--node base --manifest manifest/baseline-manifest.json"
        + " --profile " + shlex.quote(profile)
        + " --root " + shlex.quote(test_root)
    )
    bridge = test_root + "/usr/local/lib/bladerf-link/runtime/base/bladeRF-linux-mac80211.hwsim42"
    result = run(
        "set -e; rm -rf -- " + shlex.quote(test_root) + "; "
        + "./tools/install-baseline-runtime " + common + " --receipt " + shlex.quote(bash_path(install_receipt)) + "; "
        + "chmod u+w " + shlex.quote(bridge) + "; "
        + "printf X | dd of=" + shlex.quote(bridge) + " bs=1 seek=0 conv=notrunc status=none; "
        + "chmod 0555 " + shlex.quote(bridge) + "; "
        + "./tools/install-baseline-runtime --verify-only " + common + " --receipt " + shlex.quote(bash_path(failed_receipt))
    )
    assert result.returncode != 0
    assert "digest differs" in result.stderr
    assert not failed_receipt.exists()
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0


def test_verify_fails_closed_before_receipt_when_installed_runner_changes(tmp_path):
    test_root = "/tmp/bladerf-baseline-%d-runner-tamper" % os.getpid()
    install_receipt = tmp_path / "runner-tamper-install.json"
    failed_receipt = tmp_path / "runner-tamper-verify.json"
    profile = bash_path(ROOT / "configs/local/base.local-profile.example.json")
    common = "--node base --manifest manifest/baseline-manifest.json --profile " + shlex.quote(profile) + " --root " + shlex.quote(test_root)
    runner = test_root + "/usr/local/libexec/bladerf-link-node"
    result = run(
        "set -e; rm -rf -- " + shlex.quote(test_root) + "; "
        + "./tools/install-baseline-runtime " + common + " --receipt " + shlex.quote(bash_path(install_receipt)) + "; "
        + "printf '#tamper\\n' >> " + shlex.quote(runner) + "; "
        + "./tools/install-baseline-runtime --verify-only " + common + " --receipt " + shlex.quote(bash_path(failed_receipt))
    )
    assert result.returncode != 0
    assert "runner differs" in result.stderr
    assert not failed_receipt.exists()
    assert run("rm -rf -- " + shlex.quote(test_root)).returncode == 0
