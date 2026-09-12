#!/usr/bin/env bash
# Download, verify, and install one immutable switchless-nccl release.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=versions.sh
source "$ROOT/scripts/versions.sh"

RELEASE=${1:?usage: install-release.sh RELEASE [DESTINATION]}
DESTINATION=${2:-"$HOME/nccl-switchless-$RELEASE"}
ASSET="$PACKAGE_NAME.tar.gz"
BASE_URL="https://github.com/alexellis/switchless-nccl/releases/download/$RELEASE"

case "$RELEASE" in
  v[0-9]*.[0-9]*.[0-9]*) ;;
  *)
    echo "release must be a semantic version such as v0.0.1" >&2
    exit 2
    ;;
esac

test ! -e "$DESTINATION" || {
  echo "destination already exists: $DESTINATION" >&2
  exit 2
}

for command in curl mv readlink sha256sum tar; do
  command -v "$command" >/dev/null || {
    echo "missing required command: $command" >&2
    exit 1
  }
done

DOWNLOAD_DIR=$(mktemp -d)
cleanup() {
  case "$DOWNLOAD_DIR" in
    /tmp/*) rm -rf -- "$DOWNLOAD_DIR" ;;
    *) echo "refusing to remove unexpected download path: $DOWNLOAD_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

curl -fsSLo "$DOWNLOAD_DIR/$ASSET" "$BASE_URL/$ASSET"
curl -fsSLo "$DOWNLOAD_DIR/$ASSET.sha256" "$BASE_URL/$ASSET.sha256"
(
  cd "$DOWNLOAD_DIR"
  sha256sum --check "$ASSET.sha256"
)

tar -xzf "$DOWNLOAD_DIR/$ASSET" -C "$DOWNLOAD_DIR"
STAGED="$DOWNLOAD_DIR/$PACKAGE_NAME"
test -d "$STAGED"
(
  cd "$STAGED"
  sha256sum --check SHA256SUMS
)
test "$(readlink "$STAGED/libnccl.so.2")" = "libnccl.so.$NCCL_VERSION"
test "$(readlink "$STAGED/libnccl.so")" = libnccl.so.2

mkdir -p "$(dirname "$DESTINATION")"
mv "$STAGED" "$DESTINATION"
echo "installed $RELEASE at $DESTINATION"
