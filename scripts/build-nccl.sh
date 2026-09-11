#!/usr/bin/env bash
# Build the switchless NCCL library from pinned source. No GPU is required.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=versions.sh
source "$ROOT/scripts/versions.sh"

OUTPUT_DIR=${1:-$PWD/nccl-patched}
PATCH="$ROOT/patches/nccl-2.30.7-switchless-cycle.patch"

case "$(uname -m)" in
  aarch64 | arm64) ;;
  *)
    echo "this builder produces the native DGX Spark ARM64 library" >&2
    echo "run it on an ARM64 Linux host or the Actuated ARM runner" >&2
    exit 2
    ;;
esac

for command in docker file git install ln nproc readlink sha256sum strings; do
  command -v "$command" >/dev/null || {
    echo "missing required command: $command" >&2
    exit 1
  }
done

echo "$NCCL_PATCH_SHA256  $PATCH" | sha256sum --check --status - || {
  echo "patch hash does not match scripts/versions.sh" >&2
  exit 1
}

BUILD_DIR=$(mktemp -d)
cleanup() {
  case "$BUILD_DIR" in
    /tmp/*) rm -rf -- "$BUILD_DIR" ;;
    *) echo "refusing to remove unexpected build path: $BUILD_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

git clone --quiet --filter=blob:none https://github.com/NVIDIA/nccl.git \
  "$BUILD_DIR/nccl"
git -C "$BUILD_DIR/nccl" checkout --quiet "$NCCL_COMMIT"

test "$(git -C "$BUILD_DIR/nccl" write-tree)" = "$NCCL_BASE_TREE" || {
  echo "NCCL base tree does not match the provenance pin" >&2
  exit 1
}
git -C "$BUILD_DIR/nccl" apply --check "$PATCH"
git -C "$BUILD_DIR/nccl" apply --index "$PATCH"
test "$(git -C "$BUILD_DIR/nccl" write-tree)" = "$NCCL_PATCHED_TREE" || {
  echo "patched NCCL tree does not match the provenance pin" >&2
  exit 1
}

docker run --rm \
  --entrypoint bash \
  -e BUILD_JOBS="$(nproc)" \
  -e HOST_UID="$(id -u)" \
  -e HOST_GID="$(id -g)" \
  -e NCCL_CUDA_ARCH="$CUDA_ARCH" \
  -v "$BUILD_DIR/nccl:/src" \
  -w /src \
  "$CUDA_IMAGE" \
  -ceu '
    trap '\''chown -R "$HOST_UID:$HOST_GID" /src/build 2>/dev/null || true'\'' EXIT
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3
    rm -rf /var/lib/apt/lists/*
    make -j"$BUILD_JOBS" src.build \
      CUDA_HOME=/usr/local/cuda \
      NVCC_GENCODE="-gencode=arch=compute_${NCCL_CUDA_ARCH},code=sm_${NCCL_CUDA_ARCH}"
  '

install -d -m 0755 "$OUTPUT_DIR"
install -m 0755 "$BUILD_DIR/nccl/build/lib/libnccl.so.$NCCL_VERSION" \
  "$OUTPUT_DIR/libnccl.so.$NCCL_VERSION"
ln -sfn "libnccl.so.$NCCL_VERSION" "$OUTPUT_DIR/libnccl.so.2"
ln -sfn libnccl.so.2 "$OUTPUT_DIR/libnccl.so"

"$ROOT/scripts/verify-nccl.sh" "$OUTPUT_DIR"
echo "built $OUTPUT_DIR/libnccl.so.$NCCL_VERSION"
