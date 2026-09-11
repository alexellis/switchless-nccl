# Provenance

## NVIDIA NCCL source

- repository: `https://github.com/NVIDIA/nccl.git`
- release tag: `v2.30.7-1`
- commit: `73cf112295c33aee2b895f329f592f2a9b4b0f97`
- unmodified Git tree: `3e7de6f92f0190d1afe9f05642e634cbf43ae4c9`
- licence: Apache-2.0 and BSD-3-Clause; retain NVIDIA's `LICENSE.txt` and
  `ThirdPartyNotices.txt` when distributing a binary

## Switchless-cycle patch

- file: `patches/nccl-2.30.7-switchless-cycle.patch`
- SHA-256: `6709063fa1c25055ae77a9397dea5d89643f8211d25e7990bdd11597d08c0dde`
- patched Git tree: `abdeb053b94c3f6d472cd55ae2b79ca821299009`
- source repository: `https://github.com/FujitsuPolycom/sparkring`
- source commit: `a6f12fda47ebf4b0bba4c63e3facba801e7fd0b1`
- ownership: original SparkRing implementation, Apache-2.0

The patch:

1. adds the opt-in `NCCL_SWITCHLESS_RING_ONLY` parameter;
2. bypasses Tree and PAT transport setup when the parameter is enabled; and
3. advertises the eligible listener GIDs from both selected RoCE devices so
   subnet-aware selection can choose the physical cable shared with a peer.

The listener change extends NVIDIA's DGX Spark subnet-aware routing work in
commit `5c1c4288e6627e9b442eda997aa6ee9136cda0bd`, authored by Zifu Yang and
signed off by Xiaofan Li. The patch retains the surrounding NVIDIA source and
licence boundary.

## Prior art

Joseph Rose published the skip-Tree/skip-PAT approach in
`josephdrose/nccl-spark-switchless`. Its first public commit is
`27ca6d3bdc43d6c2978fc34b920cdc8a218a333a`, authored by Joseph Rose on
4 July 2026. The repository declares no licence.

No source from that repository is included here. The conceptual prior art is
credited because earlier SparkRing compatibility patches used a small guard
with the same purpose. Those compatibility patches are deliberately absent
from this repository; only the separately written SparkRing patch above is a
build input.

## Build target

- operating system: Linux
- architecture: ARM64 / AArch64
- CUDA userspace: 13.0.2 build image, pinned by digest in
  `scripts/versions.sh`
- GPU code generation: `sm_121` (DGX Spark GB10)
- output SONAME/version: `libnccl.so.2.30.7`

`scripts/build-nccl.sh` verifies the source tree, patch hash, patched tree, and
container image pin before compiling. `scripts/package-nccl.sh` bundles this
document, the exact patch, project notices, and the upstream NCCL licence and
third-party notices with the resulting library.
