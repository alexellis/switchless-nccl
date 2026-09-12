# Switchless NCCL for DGX Spark

Build, install, and verify a source-pinned NCCL library for a direct-cable
RoCE cycle of NVIDIA DGX Spark systems.

Stock NCCL attempts Tree and PAT transport connections between ranks that are
not directly cabled in a four-node switchless cycle. This branch layers a
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

After this hardened build is qualified and released, download its bundle
on every Spark, verify its checksum, and extract it to the same host path:

```bash
tar -xzf nccl-2.30.7-switchless-hardened-sm121-linux-arm64.tar.gz
install -d "$HOME/nccl-switchless"
cp -a nccl-2.30.7-switchless-hardened-sm121-linux-arm64/. \
  "$HOME/nccl-switchless/"
(cd "$HOME/nccl-switchless" && sha256sum --check SHA256SUMS)
```

For a host process, use the wrapper so PyTorch and vLLM agree on the library:

```bash
./scripts/switchless-nccl-run \
  "$HOME/nccl-switchless/libnccl.so.2" -- vllm serve ...
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

The host does not need a GPU. CI uses an ARM64 runner and publishes checksummed
release archives when a repository release/tag is created. No standalone
release has been cut yet; the current production library stays pinned during
qualification.

## Fabric configuration

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

This branch passed the four-rank value-checked collective gate and a matched
full-model A/B against the standalone combined patch. Both RigMark arms passed
15/15 outputs and were a practical performance tie. `legacy-hardened` is the
recommended four-node variant because its compatibility and fail-closed
configuration checks have no material measured cost. See
[`docs/qualification.md`](docs/qualification.md).

The exact-source baseline remains on `legacy-two-patch`.

The implemented and deferred items are recorded in
[`docs/patch-roadmap.md`](docs/patch-roadmap.md).

Licensed under Apache-2.0. See [`NOTICE`](NOTICE) and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
