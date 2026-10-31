#!/usr/bin/env bash
# Download, verify, and install one immutable switchless-nccl release.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=versions.sh
source "$ROOT/scripts/versions.sh"

PROFILE=four-pf
REPOSITORY=alexellis/switchless-nccl
POSITIONAL=()
while (( $# )); do
  case "$1" in
    --profile|--repository)
      if (( $# < 2 )) || [[ -z $2 || $2 == --* ]]; then
        echo "$1 requires a value" >&2
        exit 2
      fi
      if [[ $1 == --profile ]]; then PROFILE=$2; else REPOSITORY=$2; fi
      shift 2
      ;;
    --*) echo "unknown option: $1" >&2; exit 2 ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done
if (( ${#POSITIONAL[@]} < 1 || ${#POSITIONAL[@]} > 2 )); then
  echo 'usage: install-release.sh [--profile two-pf|four-pf] [--repository OWNER/REPO] RELEASE [DESTINATION]' >&2
  exit 2
fi
set -- "${POSITIONAL[@]}"
case "$PROFILE" in
  two-pf) destination_name=nccl-switchless ;;
  four-pf) PACKAGE_NAME=$FOUR_PF_PACKAGE_NAME; destination_name=nccl-switchless-four-pf ;;
  *) echo 'profile must be two-pf or four-pf' >&2; exit 2 ;;
esac
[[ $REPOSITORY =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo 'repository must be OWNER/REPO' >&2; exit 2;
}
RELEASE=${1:?usage: install-release.sh [--profile two-pf|four-pf] [--repository OWNER/REPO] RELEASE [DESTINATION]}
DESTINATION=${2:-"$HOME/$destination_name-$RELEASE"}
ASSET="$PACKAGE_NAME.tar.gz"
BASE_URL="https://github.com/$REPOSITORY/releases/download/$RELEASE"

case "$RELEASE" in
  v[0-9]*.[0-9]*.[0-9]*) ;;
  *)
    echo "release must be a semantic version such as v0.0.1" >&2
    exit 2
    ;;
esac

if [[ -e "$DESTINATION" || -L "$DESTINATION" ]]; then
  echo "destination already exists: $DESTINATION" >&2
  exit 2
fi

required_commands=(curl mv readlink sha256sum tar)
if [[ $PROFILE == four-pf ]]; then
  required_commands+=(python3 readelf strings)
fi
for command in "${required_commands[@]}"; do
  command -v "$command" >/dev/null || {
    echo "missing required command: $command" >&2
    exit 1
  }
done

if [[ $PROFILE == four-pf ]] && ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo 'four-PF installation requires Python 3.11 or newer' >&2
  exit 1
fi

DOWNLOAD_DIR=$(mktemp -d)
cleanup() {
  case "$DOWNLOAD_DIR" in
    /tmp/*) rm -rf -- "$DOWNLOAD_DIR" ;;
    *) echo "refusing to remove unexpected download path: $DOWNLOAD_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

if curl -fsSLo "$DOWNLOAD_DIR/$ASSET" "$BASE_URL/$ASSET"; then
  :
else
  download_status=$?
  if [[ $PROFILE == four-pf ]]; then
    echo "could not download four-PF asset $ASSET for $RELEASE; if this release has no four-PF archive, use --profile two-pf" >&2
  fi
  exit "$download_status"
fi
curl -fsSLo "$DOWNLOAD_DIR/$ASSET.sha256" "$BASE_URL/$ASSET.sha256"
(
  cd "$DOWNLOAD_DIR"
  sha256sum --check "$ASSET.sha256"
)

if [[ $PROFILE == four-pf ]]; then
  python3 "$ROOT/scripts/package-dual-pf.py" unpack "$DOWNLOAD_DIR/$ASSET" "$DOWNLOAD_DIR"
else
  tar -xzf "$DOWNLOAD_DIR/$ASSET" -C "$DOWNLOAD_DIR"
fi
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
