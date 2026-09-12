#!/usr/bin/env bash
# Package a source-built NCCL library with licences and exact provenance.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=versions.sh
source "$ROOT/scripts/versions.sh"

NCCL_DIR=${1:?usage: package-nccl.sh NCCL_DIR OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: package-nccl.sh NCCL_DIR OUTPUT_DIR}
LIBRARY="$NCCL_DIR/libnccl.so.$NCCL_VERSION"

for command in curl gzip install ln sha256sum tar; do
  command -v "$command" >/dev/null || {
    echo "missing required command: $command" >&2
    exit 1
  }
done

"$ROOT/scripts/verify-nccl.sh" "$NCCL_DIR"

PACKAGE_DIR=$(mktemp -d)
cleanup() {
  case "$PACKAGE_DIR" in
    /tmp/*) rm -rf -- "$PACKAGE_DIR" ;;
    *) echo "refusing to remove unexpected package path: $PACKAGE_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

STAGING="$PACKAGE_DIR/$PACKAGE_NAME"
install -d -m 0755 "$STAGING" "$OUTPUT_DIR"
install -m 0755 "$LIBRARY" "$STAGING/libnccl.so.$NCCL_VERSION"
ln -s "libnccl.so.$NCCL_VERSION" "$STAGING/libnccl.so.2"
ln -s libnccl.so.2 "$STAGING/libnccl.so"

install -m 0644 "$ROOT/PROVENANCE.md" "$STAGING/PROVENANCE.md"
install -m 0644 "$ROOT/LICENSE" "$STAGING/LICENSE.project.txt"
install -m 0644 "$ROOT/NOTICE" "$STAGING/NOTICE"
install -m 0644 "$ROOT/THIRD_PARTY_NOTICES.md" \
  "$STAGING/THIRD_PARTY_NOTICES.md"
install -m 0644 "$ROOT/patches/nccl-2.30.7-skip-tree-pat.patch" \
  "$STAGING/nccl-2.30.7-skip-tree-pat.patch"
install -m 0644 "$ROOT/patches/nccl-2.30.7-advertise-all-listener-gids.patch" \
  "$STAGING/nccl-2.30.7-advertise-all-listener-gids.patch"

curl -fsSL \
  "https://raw.githubusercontent.com/NVIDIA/nccl/$NCCL_COMMIT/LICENSE.txt" \
  -o "$STAGING/LICENSE.NCCL.txt"
echo "$NCCL_LICENSE_SHA256  $STAGING/LICENSE.NCCL.txt" |
  sha256sum --check --status -

curl -fsSL \
  "https://raw.githubusercontent.com/NVIDIA/nccl/$NCCL_COMMIT/ThirdPartyNotices.txt" \
  -o "$STAGING/ThirdPartyNotices.NCCL.txt"
echo "$NCCL_NOTICES_SHA256  $STAGING/ThirdPartyNotices.NCCL.txt" |
  sha256sum --check --status -

(
  cd "$STAGING"
  sha256sum \
    "libnccl.so.$NCCL_VERSION" \
    LICENSE.NCCL.txt \
    ThirdPartyNotices.NCCL.txt \
    nccl-2.30.7-skip-tree-pat.patch \
    nccl-2.30.7-advertise-all-listener-gids.patch > SHA256SUMS
)

SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct)}
ASSET="$PACKAGE_NAME.tar.gz"
tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 \
  --numeric-owner -cf - -C "$PACKAGE_DIR" "$PACKAGE_NAME" |
  gzip -n > "$OUTPUT_DIR/$ASSET"
(
  cd "$OUTPUT_DIR"
  sha256sum "$ASSET" > "$ASSET.sha256"
)

echo "packaged $OUTPUT_DIR/$ASSET"
