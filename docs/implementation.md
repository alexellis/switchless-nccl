# Canonical implementation

The repository publishes one implementation from `master`: NCCL 2.30.7 with
the two proven Apache-2.0 switchless source patches and the separately marked
OpenFaaS Ltd hardening patch.

The canonical binary is release
[`v0.0.1`](https://github.com/alexellis/switchless-nccl/releases/tag/v0.0.1).
Consumers pin its archive SHA-256
`b4a686382a92e57b485ca1bf7cd0f9fde780a68f01ea902ac432b60505b2041f`
and library SHA-256
`78cb83871792ec57d763d142e4cae26fc754ae284bcc81dcb2a7d50e17d4fa57`.

The runtime must opt in explicitly:

```text
NCCL_SWITCHLESS_RING_ONLY=1
NCCL_ALGO=Ring
NCCL_IB_SUBNET_AWARE_ROUTING=1
NCCL_IB_MERGE_NICS=0
```

The compatibility alias `NCCL_SKIP_TREE_CONNECT=1` remains accepted so an
existing deployment can move to the canonical build without changing its
launcher and library simultaneously. New deployments should use
`NCCL_SWITCHLESS_RING_ONLY=1`.

The implementation:

- preserves stock NCCL listener behaviour unless switchless mode is enabled;
- skips unsupported Tree and PAT transport setup in explicit Ring-only mode;
- rejects NIC merging;
- requires exactly two valid, distinct listener GIDs;
- emits identifiable `SWITCHLESS/HARDENED` diagnostics; and
- leaves the steady-state NCCL Ring collective path unchanged.

It passed the physical four-rank collective gate, the complete
GLM-5.3-Flash TP4 + DFlash2 serving qualification, and a second full RigMark
regression after the public release asset was installed and mapped into all
four live ranks. See
[`qualification.md`](qualification.md) for the results and
[`runtime.md`](runtime.md) for the mandatory loading contract.

The old comparison implementations are not published as branches or release
assets. Their immutable identities and measurements remain only in the
qualification record.

The project-owned hardening, tooling, documentation, and packaging are
Copyright 2026 Alex Ellis, OpenFaaS Ltd, and licensed under Apache-2.0. NVIDIA
and SparkRing retain their rights in the upstream sources recorded in
[`../PROVENANCE.md`](../PROVENANCE.md).
