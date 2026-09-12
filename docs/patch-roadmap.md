# Patch improvement roadmap

The first two files under `patches/` preserve SparkRing's known-working inputs
byte-for-byte. The third file is a separately identified OpenFaaS Ltd hardening
patch. Together they form the sole implementation published from `master`.

The following changes have clear correctness value. Their state is explicit so
that a successful transport test is not overstated.

## Make ring-only an algorithm constraint — partially implemented

The current patch returns success from the Tree and PAT transport-connect
functions without creating those connections. This works when the deployment
also forces `NCCL_ALGO=Ring`, but it leaves NCCL's internal algorithm matrix
claiming that unsupported algorithms exist.

The launch wrapper rejects a conflicting `NCCL_ALGO` and exports `Ring` before
the process starts. The deeper internal changes remain deferred:

1. restrict the effective algorithm matrix to Ring in the graph/tuning path;
2. skip eager Tree/PAT setup at its caller when ring-only mode is active;
3. cover lazy runtime connection paths as well as eager initialisation; and
4. reject an explicit conflicting `NCCL_ALGO` rather than constructing a
   communicator with missing connectors.

This removes synthetic success and makes an invalid configuration fail during
initialisation with a precise diagnostic.

## Bound listener-GID advertisement — implemented

The hardening patch preserves stock behaviour outside ring-only mode and,
inside it:

- require exactly two selected, active RoCE devices;
- require `NCCL_IB_MERGE_NICS=0`;
- select two valid, distinct GIDs deterministically;
- fail instead of silently truncating when more handle slots would be needed;
  and
- log the device, index, GID, and switchless patchset identity.

The `SWITCHLESS/HARDENED` strings let binary verification prove that both the
transport skip and listener validation were compiled.

## Validate the external contract

Before communicator creation, the operator preflight should prove that every
rank agrees on:

- patched library SHA-256 and mapped real path;
- patchset identity and ring-only mode;
- Ring as the only collective algorithm;
- two HCAs and their deterministic order;
- dynamic IPv4 RoCEv2 selection policy; and
- physical rank order around the cable cycle.

Direct send/receive between uncabled diagonal ranks remains unsupported. A
working Ring collective must not be presented as generic diagonal P2P
reachability.

## Qualification matrix

CPU/source CI should cover unset, `0`, `1`, and invalid ring-only values;
conflicting algorithm settings; and zero, one, two, duplicate, and more-than-two
eligible GIDs.

Four-Spark qualification should value-check all-reduce, all-gather,
reduce-scatter, and broadcast across sizes and protocols; exercise CUDA graph
capture/replay and repeated communicator teardown; reverse HCA enumeration;
test stale addresses and GIDs at different indices; bound the failure of an
uncabled diagonal P2P; and finish with the full vLLM model gate.
