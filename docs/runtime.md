# Runtime loading contract

The patched library must win every NCCL resolution path in every rank process.
For vLLM that means two selectors, not two separately managed services:

- `LD_PRELOAD` makes the ELF loader select the patched library for PyTorch and
  every process which inherits the environment; and
- `VLLM_NCCL_SO_PATH` tells vLLM/PyNccl which file to open explicitly instead
  of discovering a wheel-bundled copy.

`TORCH_USE_RTLD_GLOBAL=1` keeps the selected symbols visible to extensions
loaded after PyTorch. The API process, EngineCore process, and workers must all
inherit these values. On a multi-node deployment, the same contract applies to
every rank container.

## Container contract

Mount the complete verified bundle read-only at one canonical path, for example
`/opt/switchless-nccl`, then set:

```text
LD_PRELOAD=/opt/switchless-nccl/libnccl.so.2
VLLM_NCCL_SO_PATH=/opt/switchless-nccl/libnccl.so.2
TORCH_USE_RTLD_GLOBAL=1
NCCL_SKIP_TREE_CONNECT=1
NCCL_SWITCHLESS_RING_ONLY=1
NCCL_ALGO=Ring
NCCL_NET=IB
NCCL_IB_DISABLE=0
NCCL_IB_HCA=<the two neighbour-facing RoCE devices>
NCCL_IB_ROCE_VERSION_NUM=2
NCCL_IB_ADDR_FAMILY=AF_INET
NCCL_IB_SUBNET_AWARE_ROUTING=1
NCCL_IB_SUBNET_PREFIX_LEN=24
NCCL_IB_MERGE_NICS=0
NCCL_CROSS_NIC=1
NCCL_SOCKET_IFNAME=<management interface>
GLOO_SOCKET_IFNAME=<management interface>
```

`NCCL_IB_MERGE_NICS=0` is part of the topology contract. NCCL enables NIC
merging by default; leaving it implicit can make weight loading wedge before
the API starts.

On NCCL 2.21 and later, leave `NCCL_IB_GID_INDEX` unset and let NCCL select a
RoCEv2 IPv4 GID dynamically. `NCCL_IB_ADDR_FAMILY=AF_INET` and
`NCCL_IB_ROCE_VERSION_NUM=2` make that policy explicit. If the host has more
than the two dedicated fabric addresses, constrain selection with
`NCCL_IB_ADDR_RANGE=<fabric CIDR>`. The fabric reset still removes stale
addresses because one intended global IPv4 per port makes selection and
listener advertisement deterministic.

This follows NVIDIA's
[RoCE troubleshooting guidance](https://github.com/NVIDIA/nccl/blob/v2.30.7-1/docs/userguide/source/troubleshooting/networking_troubleshooting.rst#L304-L315)
and the pinned release's
[dynamic GID-selection variables](https://github.com/NVIDIA/nccl/blob/v2.30.7-1/docs/userguide/source/env.rst#L277-L327).

Older, already qualified launchers may pin the common index reported by
`fabric-apply.sh` during migration. Do not combine a hard-coded index with a
host whose two ports report different indices.

Do not enable `NCCL_SKIP_TREE_CONNECT` on a two-rank pair. Both ranks are
directly connected, so stock Tree setup is valid. Do not enable it on a
switched fabric either.

## Prove the loaded library

A path in an environment variable is not proof that the running process used
it. Inspect a live worker or run a preflight under the exact launch environment:

```bash
python3 scripts/verify-loaded.py \
  --pid WORKER_PID \
  --expected /opt/switchless-nccl/libnccl.so.2

scripts/switchless-nccl-run /opt/switchless-nccl/libnccl.so.2 -- \
  python3 scripts/verify-loaded.py \
    --expected /opt/switchless-nccl/libnccl.so.2 \
    --import-torch
```

The verifier reads `/proc/PID/maps`, resolves symlinks, and requires exactly
one NCCL library identity. It rejects both a missing library and the common
failure where the patched file and a wheel-bundled file are mapped together.

The launch wrapper also fails before `exec` unless the versioned library is
pinned by the release bundle's `SHA256SUMS`. A direct local build can provide
the expected digest explicitly as `SWITCHLESS_NCCL_SHA256`; a bare path is not
treated as an identity.

The final live gate must also observe both `SWITCHLESS: skipping` diagnostics
with `NCCL_DEBUG=INFO`, confirm Ring
selection, and complete a real multi-rank collective. Binary inspection in CI
cannot qualify the physical fabric.
