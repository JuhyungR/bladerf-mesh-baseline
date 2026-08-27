# Manifest v1

The canonical manifest is UTF-8 without BOM, lexicographically sorted object
keys, compact JSON separators, and one trailing LF. Its SHA-256 is calculated
over exactly those bytes. Firmware artifact metadata may be declared while
`firmware_state` remains `deferred`; actual bytes are prohibited before the
approved extraction gate.

After extraction, `firmware_state` is `verified` only when the three repository
firmware files exactly match the manifest paths, sizes, and SHA-256 values. The
full release verifier requires both `--firmware-root firmware` and
`--runtime-root runtime`, rejects symlinks and extra or missing files, and
validates both complete trees before reporting the verified state. The runtime
tree currently contains the checkpoint-attested Base and Jetson bridge
binaries; their source ownership/mode metadata remains provenance, while the
installer publishes both as root-owned mode `0555` executables.

The manifest declares exactly two generated environment files, one per node.
They are deterministic outputs of the canonical manifest plus an ignored local
profile and contain the source manifest digest. Profile sections are encoded as
canonical-JSON base64 values so the files remain valid systemd EnvironmentFile
inputs without recording local values in receipts.

Tracked profiles are non-live examples using documentation-only identifiers and
TEST-NET addresses. Real serial, network, and RF values belong only in ignored
local profiles. The renderer rejects extra keys, control characters, unsafe
identifiers, duplicate MACs, and IP peers outside the declared IPv4 subnet.

The sealed Jetson HWSIM byte stream declares the embedded vermagic
`4.9.337-tegra SMP preempt mod_unload modversions aarch64`. A Jetson disposable
install must match Ubuntu 18.04, aarch64, and kernel `4.9.337-tegra`.

Public manifest provenance uses neutral `/sealed-snapshots/<node>/...` labels
instead of operator usernames or live host paths. Each bundled artifact keeps
its component-specific upstream terms; attribution and the written offer for
its complete corresponding source are recorded in
`THIRD_PARTY_NOTICES.md` and `SOURCE_OFFER.md`.

Release state has independent firmware and runtime fields. Firmware and bridge
bytes may be verified while runtime remains `deferred`; that intermediate state
is not a disposable-install or release candidate. A real-root install is
rejected until the sanitized RF runner is manifest-bound and `runtime_state`
becomes `verified`.

The sanitized runner passed the focused offline lifecycle review. It
checks `NO_START` before reading generated configuration or payload bytes. A
non-root disposable test root can transition once to `EXECUTION_RESERVED` and
exercise a synthetic Base-STA or Jetson-AP lifecycle after verifying the exact
manifest digest and all node payload hashes. The actual single-attempt runner is
present as an offline candidate and includes a nonblocking node lock, Base
management-interface guard, Jetson HWSIM ownership, AP/STA readiness gates, and
bounded signal cleanup. Exact fake-backend Base and Jetson success and incident
cleanup traces exercise that same state machine without invoking host commands.
The manifest therefore records `runtime_state=verified`, while production
authority promotion remains intentionally absent and `NO_START` continues to
block real execution. The candidate configures only the RF interface
link state and association role; it does not assign IP addresses, add routes, or
run load, throughput, or capture activity.

Offline checkpoint receipts are point-in-time evidence. Earlier extraction
freeze receipts retain the release state observed at their own commit; the
latest runtime-migration receipt binds the reviewed runner, current manifest
digest, and full verified release gate without rewriting those historical facts.
