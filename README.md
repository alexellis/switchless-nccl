# Switchless NCCL for DGX Spark

Build, install, and verify a source-pinned NCCL library for a direct-cable
RoCE cycle of NVIDIA DGX Spark systems.

Stock NCCL attempts Tree and PAT transport connections between ranks that are
not directly cabled in a four-node switchless cycle. This repository layers a
separately identified hardening patch over the exact two Apache-2.0 SparkRing
files used by Alex Ellis's known-working four-Spark library.

It also packages the two operational details which are easy to miss:

- every vLLM process must resolve the same patched `libnccl.so`; and
- each fabric interface must have exactly one intended IPv4 address before its
  RoCEv2 GID index is selected.

This is not a generic replacement for stock NCCL. The patched mode is opt-in
and is intended for a directly cabled cycle whose collective algorithm is
forced to Ring. Use stock NCCL for a switched fabric or a two-node direct pair.

## Quick start

Download, verify, and install a pinned release on every Spark:

```bash
./scripts/install-release.sh --profile two-pf v0.0.1 "$HOME/nccl-switchless-v0.0.1"
```

v0.0.1 has no four-PF archive. With this installer, a default install of that tag
fails; use `--profile two-pf` as shown above.

For a host process, use the wrapper so PyTorch and vLLM agree on the library:

```bash
./scripts/switchless-nccl-run \
  "$HOME/nccl-switchless-v0.0.1/libnccl.so.2" -- vllm serve ...
```

For a container, mount the directory read-only at the same path on every rank
and inject the complete environment shown in [the runtime contract](docs/runtime.md).
The example Compose fragment is in [`examples/compose.yaml`](examples/compose.yaml).

The library remains inert unless the deployment also sets:

```text
NCCL_SWITCHLESS_RING_ONLY=1
NCCL_ALGO=Ring
NCCL_IB_SUBNET_AWARE_ROUTING=1
NCCL_IB_MERGE_NICS=0
```

Build it on an ARM64 Linux host with Docker:

```bash
./scripts/build-nccl.sh ./nccl-patched
./scripts/package-nccl.sh ./nccl-patched ./bin
```

The host does not need a GPU. ARM64 CI uploads checksummed bundles as Actions artifacts.
The existing tag-triggered publish workflow builds both profiles and publishes two distinct archives with checksums.
If either profile fails, the workflow does not upload release assets.
The default installer selects the four-PF archive. `--profile two-pf` selects the two-PF archive.

## Fabric configuration

The four-node fabric uses **four Amphenol DAC cables**, with one cable per
edge. We have tested both **NJAAKK-N911 (0.4 m)** and **NJAAKK0006 (0.5 m)**
(recorded supplier part `SF-NJAAKK0006-000.5M` for the latter):

```text
 node0 f0 +---------- cable D ----------+ f0 node3
       f1 |                            | f1
          | cable A            cable C |
       f1 |                            | f1
 node1 f0 +---------- cable B ----------+ f0 node2
```

Each node connects to two neighbours. Management Ethernet is separate.
See [the full ASCII wiring layout and cable list](docs/fabric.md#physical-wiring-four-sparks-four-cables)
for exact port-to-port connections, per-link addresses, RDMA device names,
and the management wiring.

Copy [`examples/fabric.env`](examples/fabric.env) once per node and fill in the
two fabric interfaces, permanent MAC addresses, and addresses. Then render and
apply the known-good Netplan shape:

```bash
sudo ./scripts/fabric-apply.sh ./fabric.env
```

The command refuses to touch the default-route interface, matches both NICs by
MAC, validates Netplan before changing the live network, flushes stale global
IPv4 addresses only from those two fabric NICs, applies the persistent config,
and waits for the exact IPv4 RoCEv2 GIDs. It reports, and for legacy pinned
profiles validates, the resulting indices. See [the fabric runbook](docs/fabric.md).

## Provenance

Joseph Rose first published the skip-Tree/skip-PAT switchless approach in
[`josephdrose/nccl-spark-switchless`](https://github.com/josephdrose/nccl-spark-switchless).
That repository has no declared licence, so no source from it is included here.

The first two patch files were published by SparkRing under Apache-2.0 and are
byte-for-byte identical to the live build inputs. The third patch is this
project's clearly marked modification: it adds strict NCCL parameter parsing,
keeps upstream listener behaviour outside explicit switchless mode, rejects
NIC merging, requires exactly two distinct listener GIDs, and emits an
identifiable diagnostic. Exact commits, trees, and hashes are in
[`PROVENANCE.md`](PROVENANCE.md).

## Consumers

- [`alexellis/glm-5.3-flash-4x-dgx-spark-switchless`](https://github.com/alexellis/glm-5.3-flash-4x-dgx-spark-switchless)
- [`alexellis/glm-5.3-flash-2x-dgx-spark-switchless`](https://github.com/alexellis/glm-5.3-flash-2x-dgx-spark-switchless)
- [`FujitsuPolycom/sparkring`](https://github.com/FujitsuPolycom/sparkring)

Model-specific launchers, weights, serving images, and benchmark claims stay in
their respective repositories. This repository owns only the NCCL build,
loading contract, fabric bootstrap, and transport-level verification.

## Status

Release [`v0.0.1`](https://github.com/alexellis/switchless-nccl/releases/tag/v0.0.1)
is the canonical ARM64 build from `master`. Its release identities are:

- archive SHA-256:
  `b4a686382a92e57b485ca1bf7cd0f9fde780a68f01ea902ac432b60505b2041f`;
- `libnccl.so.2.30.7` SHA-256:
  `78cb83871792ec57d763d142e4cae26fc754ae284bcc81dcb2a7d50e17d4fa57`.

The released library passed the four-rank value-checked collective gate and
was mapped into every live GLM-5.3-Flash TP4 rank for a matched full RigMark
regression. Both RigMark arms passed 15/15 outputs; single-stream decode and
64k prefill were within 2%, with mixed concurrency movement inside overlapping
sample ranges. This two-PF release is the build covered by that serving check. The four-PF
profile below is the installer default; its runtime qualification is still open. See
[`docs/qualification.md`](docs/qualification.md).

The implemented and deferred items are recorded in
[`docs/patch-roadmap.md`](docs/patch-roadmap.md).
The sole implementation and migration contract are summarised in
[`docs/implementation.md`](docs/implementation.md).

Original project work is Copyright 2026 Alex Ellis, OpenFaaS Ltd, and licensed
under Apache-2.0. See [`NOTICE`](NOTICE) and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Four-PF (dual PCI-root) profile

For a cycle where each Spark reaches each neighbour through two PCIe-root
functions (four RoCE PFs per node), a source profile adds four-GID
listener advertisement, PCI-root-preserving routing and strict listener
admission. It is the installer default and takes effect only with its library and environment.
The four-PF release archive has a separate name from the two-device archive.
To install the two-PF archive instead, pass `--profile two-pf`.

```bash
./scripts/install-release.sh --repository othexmr/switchless-nccl \
  vX.Y.Z "$HOME/nccl-switchless-four-pf-vX.Y.Z"
```

Replace `vX.Y.Z` with a tag that includes the four-PF archive.
Omit `--repository` for releases from `alexellis/switchless-nccl`.
The archive includes configuration examples, all four patches, licenses, and source and build receipts.
The receipts identify a compiled library. They do not establish serving qualification.
See
[docs/dual-pf.md](docs/dual-pf.md).
