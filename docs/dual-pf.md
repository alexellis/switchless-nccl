# Four-PF (dual PCI-root) Ring profile

An opt-in NCCL build for a four-Spark switchless cycle where each Spark reaches
each neighbour through **two PCIe-root functions**. That gives four RoCE PFs per
node: two per cable, one on each PCI root.

The two-device build and archive keep their existing identity.
The tag-triggered publish workflow also builds and packages this profile as a separate release asset.
The installer selects this profile by default. `--profile two-pf` selects the two-device archive.
This profile takes effect only with its library and environment.

## What it adds

The fourth patch, `patches/nccl-2.30.7-dual-pf.patch`, applies on top of the
existing three:

- **Extended listener advertisement** (`NCCL_IB_EXTENDED_IPV4_GIDS=1`). A listener
  can publish up to four IPv4-mapped GIDs.
  - The extension uses a tagged format field in padding that the existing
    producer already zeroes.
  - Every legacy offset is kept, and the handle stays at 112 bytes, below
    `NCCL_NET_HANDLE_MAXSIZE`.
  - Old and new peers interoperate: an all-zero tag keeps the two-GID path, and
    an unknown tag is an error.
- **PCI-root-preserving route selection** (`NCCL_IB_PRESERVE_PCI_DOMAIN=1`). When
  the topology-selected device can't reach the peer's subnet, a reachable device
  on the same PCI root is preferred before NCCL's global first match.
- **Strict listener admission** in switchless mode (`NCCL_SWITCHLESS_RING_ONLY=1`,
  or the legacy `NCCL_SKIP_TREE_CONNECT`).
  - **Two-PF mode:** exactly two cable /24 subnets.
  - **Four-PF mode:** two PFs on each of two PCI roots, in either addressing
    layout:
    - **per cable:** two /24s, one per cable, each holding one PF from each PCI root;
    - **per function:** four distinct /24s, one per PF, as in NVIDIA's p0-to-p1
      clustering playbook.
  - **Refused:** duplicates, truncated lists, more than four candidates, and
    network, broadcast, loopback, zero or multicast addresses.
  - **Fabric:** any unicast IPv4 fabric works. A cable is identified by the full
    /24 prefix, and no address range is hard-coded.
  - **Switchless and extended both off:** only the topology-selected device is
    published, as before.
- **Route diagnostics** (`NCCL_IB_ROUTE_DIAGNOSTICS=1`, INFO/NET). One line per
  final QP: side, HCA, port, local and remote GID.

SparkRing's [dual-domain patch](https://github.com/FujitsuPolycom/sparkring/blob/ae38b0f11df4dece04673ba8549befc7e527bdf5/spark_transport/nccl/nccl-2.30.7-dual-pci-domain.patch)
already provides four-GID encoding and PCI-root preference. This profile differs
in its stricter listener admission and its backward-compatible handle extension.
It does not claim a speed advantage over SparkRing.

## Build

Prepare the patched source from a local NCCL checkout that contains
`73cf112295c33aee2b895f329f592f2a9b4b0f97`:

```sh
python3 scripts/prepare_dual_pf.py --nccl-source /path/to/nccl --output /path/to/new-dir
```

The helper:
- checks every patch hash;
- applies the stack in a fresh clone;
- requires the Git tree pinned in `profiles/dual-pf.json`;
- writes `receipt.json` and `build-plan.json`.

It doesn't fetch, build or install anything, and it refuses an existing output
directory.

Build on Linux AArch64 with CUDA 13.0:

```sh
make -C /path/to/new-dir/source -j4 src.build CUDA_HOME=/usr/local/cuda-13.0 \
  NVCC_GENCODE='-gencode=arch=compute_121,code=sm_121'
```

Or build in the pinned CUDA container on any ARM64 Linux host with Docker:

```sh
./scripts/build-dual-pf-ci.sh /absolute/path/to/new-dir
```

The four-PF packager checks the source tree, binary markers, licenses, and source and build receipts:

```sh
python3 ./scripts/package-dual-pf.py package /absolute/path/to/new-dir ./bin
```

It creates `nccl-2.30.7-switchless-four-pf-sm121-linux-arm64.tar.gz` and its checksum.
The archive includes NCCL licenses, all four patches, configuration files, and receipts.
It preserves `runtime_qualified: false` because compilation does not establish collective or serving qualification.
The two-PF packager and binary verifier remain specific to the two-PF profile.

## Release installation

Use this installer with a published release tag. The four-PF profile is the installer default.

Four-PF installation requires Python 3.11 or newer, `readelf`, and `strings`
in addition to the two-PF installer tools. These requirements are checked before downloading.

```sh
./scripts/install-release.sh --repository othexmr/switchless-nccl \
  vX.Y.Z "$HOME/nccl-switchless-four-pf-vX.Y.Z"
```

Replace `vX.Y.Z` with a published tag that includes the four-PF archive.
A default install of a release without it, such as v0.0.1, fails and names
`--profile two-pf` in its error. It does not fall back silently.
Omit `--repository` for releases from `alexellis/switchless-nccl`.
For the four-PF archive, the installer checks the archive checksum, every file checksum, the pinned profile, receipts, binary markers, and symlinks.
It refuses an existing destination.
It copies files into that destination and does not change a service, network, or system library.
Use the included `scripts/render-dual-pf-env.py` and `examples/dual-pf.json` to configure each rank.

The existing publish job builds and packages both profiles before it uploads any release assets.
A four-PF failure stops the upload and retains build evidence as an Actions artifact.
No second publish workflow is required.

## Configure

Copy [`examples/dual-pf.json`](../examples/dual-pf.json), fill in one rank's
values and render the environment:

```sh
python3 scripts/render-dual-pf-env.py node.json > node.env && . ./node.env
```

| Field | Meaning |
|---|---|
| `hcas` | Four exact HCA names |
| `fabric_addresses` | The four local IPv4 addresses, in the same order as `hcas`: either two per cable /24 on two different /24s, or four distinct per-function /24s. |
| `fabric_cidr` | A CIDR containing all four addresses |
| `socket_ifname` | The management interface for NCCL and Gloo bootstrap |

The output sets `NCCL_IB_HCA`, `NCCL_IB_ADDR_RANGE`, `NCCL_SOCKET_IFNAME` and
`GLOO_SOCKET_IFNAME`, plus the profile's fixed settings:

- Ring only;
- no NIC merging;
- /24 subnet-aware routing;
- extended GIDs;
- PCI-root preference;
- diagnostics.

It also clears an inherited `NCCL_IB_GID_INDEX`. The renderer only validates what
you declare. Check on every rank that the addresses, HCAs and cabling really form
the two-root × two-cable layout.

## Verify before use

The repository tests are CPU-only:

```sh
NCCL_SOURCE=/path/to/nccl python3 -m unittest discover -s tests -p test_dual_pf.py -v
```

They cover:
- patch identity and the pinned tree;
- the handle codec and legacy compatibility;
- the listener policy and switchless alias;
- config rendering and refusal of bad input;
- the build wrapper's failure handling.

Before serving with a rebuilt library, run a four-rank collective test with
changing payloads (eager and CUDA graph). Confirm from the route diagnostics and
per-HCA counters that all four PFs carry traffic.

## Measured results

Measured on a four-Spark switchless cycle (DGX Spark, CUDA 13.0, NCCL 2.30.7). Each Spark is direct-cabled to its two
neighbours, with two PFs per cable on separate PCI roots. The library was built from this branch: patched tree
`3b71d59c`, aarch64 `libnccl.so.2.30.7`, SHA256 `7c76d65e…0fd3`. Every rank loaded identical bytes.

The run compared this profile (all four PFs) with this repository's two-PF release. Both ran the same
four-rank BF16 all-reduce sweep, 4 KiB to 256 MiB, in interleaved rounds. The figures are pooled median bus bandwidth
over two rounds and four ranks:

| Message | Four-PF profile | Two-PF release | Gain |
|---|---:|---:|---:|
| 16 MiB | 22.50 GB/s | 13.46 GB/s | 1.67× |
| 64 MiB | 22.92 GB/s | 13.52 GB/s | 1.70× |
| 256 MiB | 23.23 GB/s | 13.79 GB/s | 1.68× |

The run also checked:

- **Correctness:** three changing payloads per size, eager and through a CUDA-graph replay, were bitwise exact on
  every rank and size.
- **Engagement:** per-HCA `port_xmit_data` counters show every used port splitting traffic 30–70 % across its two PFs.
  The route diagnostics show every rank connecting on all four HCAs, on both PCI roots.

### Per-function addressing

A second run checked the per-function layout. The library was built from this branch with per-function admission:
patched tree `50ffad54`, aarch64 `libnccl.so.2.30.7`, SHA256 `db508c9c…2802`. Each PF got its own /24 next to its
per-cable address, and `NCCL_IB_ADDR_RANGE` selected one layout per arm. Both layouts ran the same sweep with the
same library, in interleaved rounds:

| Message | Per function | Per cable | Ratio |
|---|---:|---:|---:|
| 16 MiB | 22.54 GB/s | 22.67 GB/s | 0.99× |
| 64 MiB | 22.00 GB/s | 22.96 GB/s | 0.96× |
| 256 MiB | 23.25 GB/s | 23.19 GB/s | 1.00× |

The per-function run passed the same correctness and engagement checks. Per-function addressing is supported and
performs in line with per-cable addressing; it is not claimed to be faster.

Small messages (≤ 1 MiB) were within run-to-run noise of the two-PF release and are not claimed. This is a
collective benchmark on one fabric, not an end-to-end serving result.

## Limits

- Ring only. Tree, PAT, diagonal P2P, IPv6, generic InfiniBand and two-node
  setups are not covered.
- Addresses are matched by /24 prefix: one /24 per cable, or one per PF.

## Attribution

NVIDIA owns NCCL and its subnet-aware routing. SparkRing published the original
skip-Tree/PAT and listener patches. Alex Ellis / OpenFaaS Ltd added the hardening
patch this builds on. The four-PF patch and tooling are Apache-2.0, and existing
notices are kept. See [PROVENANCE.md](../PROVENANCE.md).
