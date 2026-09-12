# Third-party notices

## NVIDIA NCCL

The unified diff under `patches/` contains context and removed lines from
NVIDIA NCCL at the exact revision recorded in `PROVENANCE.md`.

Copyright (c) 2015-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.

NCCL is licensed under Apache-2.0 and includes BSD-licensed portions. NCCL is
not vendored in this Git repository. A release bundle includes the upstream
`LICENSE.txt` and `ThirdPartyNotices.txt` obtained from the pinned revision.

## SparkRing

The lines added by the two patch files under `patches/` were first published by
SparkRing under Apache-2.0 at the revision recorded in `PROVENANCE.md`.
The additional hardening patch is a marked modification of those files and is
distributed under this project's Apache-2.0 licence.

## Joseph Rose's prior work

The switchless skip-Tree/skip-PAT approach was first published in
`josephdrose/nccl-spark-switchless`. That repository declares no licence.
This repository contains no source from it and records conceptual credit only.
