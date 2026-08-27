# bladeRF Meshnet Baseline

Clean, no-start baseline for the paired Base and Jetson bladeRF link. Both
nodes stay in one repository so a release binds one compatible manifest,
installer, runtime, firmware set, and test suite.

- Base payload: `firmware/base/`, `runtime/base/`, and the Base systemd unit.
- Jetson payload: `firmware/jetson/`, `runtime/jetson/`, and the Jetson systemd
  unit.
- Shared contract: `manifest/`, `schema/`, `baseline_manifest.py`, and
  `tools/`.

Installation is fail-closed and leaves the selected node static,
inactive/stopped, and blocked by `NO_START`. It never starts RF.

During a separately approved controlled start, the Base waits for association
for at most 120 seconds while both the bridge and `wpa_supplicant` remain
alive. The Jetson AP readiness window remains 5 seconds. Either child exiting
or either bounded readiness window expiring fails the single attempt.

The repository is installable and byte-verifiable. Controlled operator testing
confirmed that the verified paired-node configuration can establish an
end-to-end IP link. Packet loss, latency, association time, and throughput vary
with hardware condition, RF environment, antennas, host load, and local
configuration; this repository does not publish or guarantee universal
performance figures. Raw live-run measurements remain in private operator
records rather than this release README.

Earlier experimental variants did not meet the acceptance criteria used for
this baseline. Only the paired verified configuration described below should
be treated as supported.

## Verified hardware and OS boundary

This release is a paired, hardware-specific baseline. It is not a generic
Jetson or generic Linux SDR package.

| Node | Verified reference host | Verified OS and architecture | Verified kernel boundary | SDR |
| --- | --- | --- | --- | --- |
| Base | Lenovo Legion Y540-15IRH notebook (observed reference host) | Ubuntu 24.04 x86_64 with systemd | **exactly `6.8.0-136-generic`** | one bladeRF xA9 over USB 3.x SuperSpeed |
| Jetson | **NVIDIA Jetson Nano** | Ubuntu 18.04 aarch64 with systemd | **exactly `4.9.337-tegra`** | one bladeRF xA9 over USB 3.x SuperSpeed |

Both verified bladeRF devices reported firmware
`2.6.0-git-09c82087`. Full device serials and live network/RF values belong in
ignored local profiles and are not committed.

The installer enforces the supported OS and architecture, required host
commands, and the Jetson kernel boundary. Host model, Base kernel, bladeRF
model/serial/firmware, and USB SuperSpeed are verified in the operator's live
preflight before promotion; they are recorded compatibility facts, not claims
that the installer can discover or guarantee them.

The bundled Jetson `mac80211_hwsim.ko` has vermagic for
`4.9.337-tegra`/aarch64. Jetson Xavier, Orin, other Jetson models, other Jetson
kernels, and other Linux distributions are **not validated and must not use
this release as-is**. They require separately rebuilt runtime artifacts and a
new hardware acceptance. The Base and Jetson bridge/RBF payloads are also
node-specific and must not be exchanged between nodes.

Required host commands are checked before a production installation mutates
the filesystem:

- Both nodes: `python3`, `systemctl`, `ip`, `iw`, `bladeRF-cli`, `modprobe`,
  and `rmmod`.
- Base: `nmcli`, `wpa_supplicant`, and `ping`.
- Jetson: `hostapd` and `insmod`.

These prerequisite commands are expected on the verified Ubuntu hosts above.
Package names and availability may differ elsewhere, and other environments
are unsupported. The installer does not install OS packages automatically.

## Validate a checkout

The validation path is hardware-free and does not start RF:

```bash
python -m pytest -q
python tools/build-baseline-release.py \
  --verify-only \
  --manifest manifest/baseline-manifest.json \
  --firmware-root firmware \
  --runtime-root runtime
```

## Install Base or Jetson

Only run the installer on the verified Base and Jetson environments described
above. Use one installer for both nodes. Copy the matching example profile to
a non-example `.json` file under `configs/local/`, fill in local values, and
run:

```bash
# Base
sudo ./tools/install-baseline-runtime \
  --node base \
  --manifest manifest/baseline-manifest.json \
  --profile configs/local/base.json \
  --receipt ./base-install.json

# Jetson
sudo ./tools/install-baseline-runtime \
  --node jetson \
  --manifest manifest/baseline-manifest.json \
  --profile configs/local/jetson.json \
  --receipt ./jetson-install.json
```

Real local profiles are ignored by Git. A successful installation remains
`NO_START`; RF execution requires a separate reviewed promotion.

## Controlled link start and stop

The following procedure applies only to the verified paired-node baseline and
must be re-qualified for any other hardware, kernel, or distribution. After
both installations and their receipts have passed, use real ignored profiles
containing the matching bladeRF serials and local network values. Starting is
a controlled live-RF action. Start Jetson AP first, then Base STA, and do not
retry an ambiguous or failed attempt.

```bash
# Jetson first
sudo /usr/local/sbin/bladerf-project-admin promote-execution jetson
sudo systemctl start bladerf-link-jetson.service

# Base second
sudo /usr/local/sbin/bladerf-project-admin promote-execution base
sudo systemctl start bladerf-link-base.service
```

The runtime applies the profile's `rf_ip_cidr` and fixed peer route before
starting the bridge and AP/STA process. Base uses the sealed runtime's
half-rate mode (`-H`); Jetson uses its normal rate and hostapd beacon interval
100. Once Base has observed `CTRL-EVENT-CONNECTED`, it starts an owned
`ping -n -I <rf-interface> -i 5 <peer-ip>` keepalive. The keepalive is a
runtime child: unexpected exit fails the attempt, and cleanup stops it before
the STA/AP and bridge processes.
After readiness, verify the canonical service status and test the peer IP. Stop
in the reverse direction, Base then Jetson; IP addresses are removed during
runtime cleanup. On an installed node, run the admin status command with
`sudo`; an unreadable or malformed installed authority boundary fails closed
rather than reporting checkout-only safe defaults.

```bash
# Base first
sudo systemctl stop bladerf-link-base.service
sudo /usr/local/sbin/bladerf-project-admin remove-start-promotion base

# Jetson second
sudo systemctl stop bladerf-link-jetson.service
sudo /usr/local/sbin/bladerf-project-admin remove-start-promotion jetson
```

Promotion is accepted only from a stopped-clean state. Removal returns the
node to `NO_START`; neither admin command starts, stops, or restarts a service.

## License and corresponding source

Project-authored source and scripts are distributed under GPL-2.0-or-later
unless a file states otherwise. Bundled FPGA, bridge, and kernel-module
artifacts remain subject to their component-specific upstream licenses.
See `THIRD_PARTY_NOTICES.md` for upstream attribution and `SOURCE_OFFER.md` for
the corresponding-source offer that accompanies the executable artifacts.
