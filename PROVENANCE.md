# Provenance

## NVIDIA NCCL source

- repository: `https://github.com/NVIDIA/nccl.git`
- release tag: `v2.30.7-1`
- commit: `73cf112295c33aee2b895f329f592f2a9b4b0f97`
- unmodified Git tree: `3e7de6f92f0190d1afe9f05642e634cbf43ae4c9`
- licence: Apache-2.0 and BSD-3-Clause; retain NVIDIA's `LICENSE.txt` and
  `ThirdPartyNotices.txt` when distributing a binary

## Proven two-patch source

- files:
  - `patches/nccl-2.30.7-skip-tree-pat.patch`
  - `patches/nccl-2.30.7-advertise-all-listener-gids.patch`
- SHA-256:
  - `097656d07a5774919f0d51558b51ec05de8168c0097ed6cb7764c33230ba6eb2`
  - `dccfce86d14c15c39f0e0a742863960205a3d9823c464b31a7f7389354844178`
- patched Git tree: `9e80bc2489864b4e6c6e2184af8797b07baa68f1`
- source repository: `https://github.com/FujitsuPolycom/sparkring`
- first source commit: `b9b2225363c45ea76139493153c7756769ae5de5`
- ownership: SparkRing, Apache-2.0

The patches:

1. bypass Tree and PAT transport setup when `NCCL_SKIP_TREE_CONNECT` exists;
   and
2. advertise the eligible listener GIDs from both selected RoCE devices so
   subnet-aware selection can choose the physical cable shared with a peer.

They are byte-for-byte identical to the two files retained in
`/home/alex/nccl-build` on the qualified four-Spark deployment. Its live
`libnccl.so.2.30.7` has SHA-256
`ccd57342449c3f680befcb379329b935746e5299dc4de5f2516146e0411bd85f`.

## OpenFaaS Ltd hardening patch

- file: `patches/nccl-2.30.7-hardened-switchless.patch`
- SHA-256: `e2dd39eaefc022f99d5a3d3195e81947da20a4c7acbf1d688b4df8f6691c210c`
- final patched Git tree: `560ba01b9becbc7d3daa1677f0216503fc3be631`
- ownership: Alex Ellis, OpenFaaS Ltd, Apache-2.0

The modification is visibly marked in both affected NVIDIA source files. It:

1. replaces raw `getenv` presence checks with cached NCCL integer parameters;
2. retains `NCCL_SKIP_TREE_CONNECT` as a parsed compatibility alias;
3. makes the broader listener advertisement conditional on explicit
   switchless mode, preserving upstream behaviour otherwise;
4. rejects NIC merging in switchless mode;
5. requires exactly two distinct, valid listener GIDs instead of silently
   truncating the device walk; and
6. logs an unambiguous patch identity plus device, port, GID index, and value.

Ring-only algorithm enforcement remains in `scripts/switchless-nccl-run`.
Changing NCCL's internal tuning matrix is deliberately deferred until it can
be tested independently; returning synthetic success from Tree and PAT remains
an acknowledged limitation of this candidate.

The listener change extends NVIDIA's DGX Spark subnet-aware routing work in
commit `5c1c4288e6627e9b442eda997aa6ee9136cda0bd`, authored by Zifu Yang and
signed off by Xiaofan Li. The patch retains the surrounding NVIDIA source and
licence boundary.

## Prior art

Joseph Rose published the skip-Tree/skip-PAT approach in
`josephdrose/nccl-spark-switchless`. Its first public commit is
`27ca6d3bdc43d6c2978fc34b920cdc8a218a333a`, authored by Joseph Rose on
4 July 2026. The repository declares no licence.

No source from Joseph Rose's repository is included here. The conceptual prior
art is credited. The build inputs are the separately published SparkRing files
identified and licensed above.

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
