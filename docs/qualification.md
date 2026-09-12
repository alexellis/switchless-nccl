# Four-Spark qualification

The hardened implementation now published on `master` was qualified on
12 September 2026 against a retired standalone combined candidate. The result
is a practical performance tie, with stronger configuration safety in the
hardened implementation.

## Candidates

| Variant | NCCL library SHA-256 | Source relationship |
|---|---|---|
| Retired standalone combined | `49adf0bd8a1b18287f28fc97e13c948834cbb51829e0c886d2902e8aea93a538` | Later SparkRing combined patch used only as a qualification control |
| Canonical hardened | `34b2d81f528abae15b60fc1ea6a20da4aace7ec45c2dca1c3e93dc0fc06b4da6` | Exact proven two-patch inputs plus the marked OpenFaaS Ltd hardening patch |

The retained live legacy library, SHA-256
`ccd57342449c3f680befcb379329b935746e5299dc4de5f2516146e0411bd85f`,
also passed the transport gate. Binary hashes differ because the historical
build environment was not retained; the two legacy source patch files are
byte-for-byte identical.

## Transport gate

Each candidate ran on the physical four-Spark RoCE cycle with one rank per
node. The gate verified the versioned library SHA on every host and proved that
the process-global `ncclGetVersion` symbol resolved to the mounted candidate.
It then:

- observed candidate-specific ring, Tree, and PAT diagnostics;
- value-checked all-reduce, all-gather, reduce-scatter, and broadcast at
  1 MiB and 64 MiB;
- captured and replayed CUDA-graph all-reduce; and
- cleanly destroyed the communicator on all four ranks.

The retained historical build, retired combined candidate, and canonical
hardened implementation all passed. Single-operation transport timings are
diagnostic only and are not used for the performance verdict.

## Matched full-model A/B

Both candidates served the same LibertAIDAI GLM-5.3-Flash NVFP4 checkpoint and
DFlash2 `k=7` drafter at TP4. Hardware, physical rank order, fabric reset,
per-rank serving images, model and draft files, 262,144-token context, FP8 E4M3
KV, 12 GiB KV per rank, scheduler, chat template, cache directory, and launch
script were identical. Every rank verified the candidate SHA before starting.

Before benchmarking, both arms passed the same service gate:

- 28,780-token needle retrieval;
- GLM `glm47` tool-call parsing; and
- warm code decode in the expected 70–76 tok/s band.

RigMark revision `d8353e93b274e8d880ab14a5df2a55c87d7bee16`, protocol
1.0.0, ran the same prompts, request body, five decode samples, three prefill
samples, three concurrency samples, and seed for each arm.

| Metric | Retired combined | Canonical hardened | Hardened / combined |
|---|---:|---:|---:|
| Code decode | 72.6 tok/s | 71.0 tok/s | 0.98× |
| Prose decode | 30.8 tok/s | 30.6 tok/s | 0.99× |
| Structured ceiling | 106.5 tok/s | 109.3 tok/s | 1.03× |
| 64k cold prefill | 1,958.6 tok/s | 1,976.1 tok/s | 1.01× |
| 64k cached replay | 35,765.8 tok/s | 36,333.5 tok/s | 1.02× |
| C4 short-code load | 103.0 tok/s | 100.0 tok/s | 0.97× |

Both receipts passed 15/15 output gates. Their SHA-256 identities are:

- retired standalone combined:
  `f518209fd60e767d9c120ba071aace2a758bca0dc4876b855177aa8d90513d3d`;
- canonical hardened:
  `48d69adca14e76dabc073c7c72e7600f77a43ae5ffd3f213c12de6cad3b82956`.

The publishable copies live in the GLM TP4 recipe's `data/rigmark` directory.
Only site-specific hostnames in metadata were normalised to rank labels;
generated outputs, request settings, and timing samples are unchanged.

The observed differences are small, mixed in direction, and inside the sample
ranges. There is no evidence of a material performance regression from the
hardening layer.

## Recommendation

Use the canonical hardened implementation on `master` for the four-node
switchless cycle. It keeps the exact source lineage already proven by the live
deployment and adds:

- parsed zero/one semantics instead of raw environment-variable presence;
- the new `NCCL_SWITCHLESS_RING_ONLY` name plus the legacy
  `NCCL_SKIP_TREE_CONNECT` compatibility alias;
- upstream listener behaviour when switchless mode is not enabled;
- a hard failure if NIC merging is enabled;
- an exact two-distinct-GID contract instead of silent truncation; and
- unmistakable `SWITCHLESS/HARDENED` runtime diagnostics.

The retired standalone combined patch remains in the immutable qualification
receipt only. It does not offer a measured performance advantage large enough
to outweigh the canonical implementation's compatibility and fail-closed
checks.
