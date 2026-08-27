# Third-party notices

This release aggregates project-specific installation and safety tooling with
binary artifacts derived from the following GPL-licensed projects:

- Nuand `bladeRF-wiphy` (GPL-2.0-only):
  https://github.com/Nuand/bladeRF-wiphy
- Nuand `bladeRF` FPGA platform sources (mixed open-source licenses; the
  relevant notices are retained in the corresponding source):
  https://github.com/Nuand/bladeRF
- Nuand `bladeRF-linux-mac80211` (GPL-2.0-or-later):
  https://github.com/Nuand/bladeRF-linux-mac80211
- Nuand `bladeRF-mac80211_hwsim` and the Linux `mac80211_hwsim` code from
  which the Jetson module is derived (GPL-2.0-only):
  https://github.com/Nuand/bladeRF-mac80211_hwsim

The files under `firmware/` and `runtime/` retain their exact verified release
bytes. Their SHA-256 digests and compatibility metadata are fixed by
`manifest/baseline-manifest.json`. The RBF artifacts combine the GPLv2
`bladeRF-wiphy` design with the separately licensed bladeRF FPGA platform;
their applicable notices therefore come from the corresponding source tree
rather than a single repository-wide SPDX identifier.

To preserve the verified byte streams, the Base and Jetson bridge binaries and
the Jetson kernel module still contain historical local build-path strings.
Those strings are build provenance only; they contain no credentials or live
network configuration. Public text manifests use neutral sealed-snapshot labels.

The full corresponding source, project-specific patches, build inputs, and
available build receipts for these exact binaries are covered by
`SOURCE_OFFER.md`.
