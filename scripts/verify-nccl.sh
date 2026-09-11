#!/usr/bin/env bash
# Verify the architecture, version, patch markers, and symlinks of a build.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=versions.sh
source "$ROOT/scripts/versions.sh"

NCCL_DIR=${1:?usage: verify-nccl.sh NCCL_DIR}
LIBRARY="$NCCL_DIR/libnccl.so.$NCCL_VERSION"

for command in file readlink sha256sum strings; do
  command -v "$command" >/dev/null || {
    echo "missing required command: $command" >&2
    exit 1
  }
done

test -f "$LIBRARY" || {
  echo "missing $LIBRARY" >&2
  exit 1
}

file "$LIBRARY" | grep -E 'ARM aarch64|ARM64' >/dev/null
strings "$LIBRARY" |
  grep -F "NCCL version $NCCL_VERSION compiled with CUDA 13.0" >/dev/null
strings "$LIBRARY" |
  grep -F 'Tree transport setup disabled by NCCL_SWITCHLESS_RING_ONLY' >/dev/null
strings "$LIBRARY" |
  grep -F 'PAT transport setup disabled by NCCL_SWITCHLESS_RING_ONLY' >/dev/null

test -L "$NCCL_DIR/libnccl.so.2"
test "$(readlink "$NCCL_DIR/libnccl.so.2")" = "libnccl.so.$NCCL_VERSION"
test -L "$NCCL_DIR/libnccl.so"
test "$(readlink "$NCCL_DIR/libnccl.so")" = libnccl.so.2

sha256sum "$LIBRARY"
echo "verified $LIBRARY"
