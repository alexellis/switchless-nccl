#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=versions.sh
source "$ROOT/scripts/versions.sh"

scripts_to_lint=()
for script in "$ROOT"/scripts/*.sh "$ROOT"/scripts/switchless-nccl-run; do
  bash -n "$script"
  case "$script" in
    */versions.sh) ;;
    *) scripts_to_lint+=("$script") ;;
  esac
done
if command -v shellcheck >/dev/null; then
  shellcheck -x -P "$ROOT/scripts" "${scripts_to_lint[@]}"
fi

python3 - "$ROOT/scripts/verify-loaded.py" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
compile(source, sys.argv[1], "exec")
PY

echo "$NCCL_SKIP_PATCH_SHA256  $ROOT/patches/nccl-2.30.7-skip-tree-pat.patch" |
  sha256sum --check --status -
echo "$NCCL_GID_PATCH_SHA256  $ROOT/patches/nccl-2.30.7-advertise-all-listener-gids.patch" |
  sha256sum --check --status -

rendered=$("$ROOT/scripts/render-netplan.sh" "$ROOT/examples/fabric.env")
grep -F 'renderer: NetworkManager' <<<"$rendered" >/dev/null
grep -F 'link-local: []' <<<"$rendered" >/dev/null
grep -F 'mtu: 9000' <<<"$rendered" >/dev/null

CHECK_DIR=$(mktemp -d)
cleanup() {
  case "$CHECK_DIR" in
    /tmp/*) rm -rf -- "$CHECK_DIR" ;;
    *) echo "refusing to remove unexpected check path: $CHECK_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

git clone --quiet --filter=blob:none https://github.com/NVIDIA/nccl.git \
  "$CHECK_DIR/nccl"
git -C "$CHECK_DIR/nccl" checkout --quiet "$NCCL_COMMIT"
test "$(git -C "$CHECK_DIR/nccl" write-tree)" = "$NCCL_BASE_TREE"
for patch in \
  "$ROOT/patches/nccl-2.30.7-skip-tree-pat.patch" \
  "$ROOT/patches/nccl-2.30.7-advertise-all-listener-gids.patch"; do
  git -C "$CHECK_DIR/nccl" apply --check "$patch"
  git -C "$CHECK_DIR/nccl" apply --index "$patch"
done
test "$(git -C "$CHECK_DIR/nccl" write-tree)" = "$NCCL_PATCHED_TREE"

echo "source pins, patch, scripts, and Netplan template passed"
