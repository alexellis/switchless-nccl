#!/usr/bin/env bash
# Apply the persistent fabric config and normalise its IPv4 RoCEv2 GID slots.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONFIG=${1:?usage: fabric-apply.sh CONFIG}

test "$(id -u)" -eq 0 || {
  echo "run this command with sudo" >&2
  exit 1
}
test -f "$CONFIG" || { echo "config not found: $CONFIG" >&2; exit 1; }

# shellcheck disable=SC1090
source "$CONFIG"
NETPLAN_FILE=${NETPLAN_FILE:-/etc/netplan/90-switchless-fabric.yaml}

for name in \
  FABRIC0_IF FABRIC0_MAC FABRIC0_ADDRESS \
  FABRIC1_IF FABRIC1_MAC FABRIC1_ADDRESS; do
  test -n "${!name:-}" || { echo "missing $name" >&2; exit 1; }
done

for command in awk install ip netplan python3 readlink seq show_gids; do
  command -v "$command" >/dev/null || {
    echo "missing required command: $command" >&2
    exit 1
  }
done

case "$NETPLAN_FILE" in
  /etc/netplan/*.yaml) ;;
  *) echo "NETPLAN_FILE must be one YAML file under /etc/netplan" >&2; exit 1 ;;
esac

for interface in "$FABRIC0_IF" "$FABRIC1_IF"; do
  test -e "/sys/class/net/$interface" || {
    echo "interface not found: $interface" >&2
    exit 1
  }
done

actual_mac() { tr 'A-F' 'a-f' < "/sys/class/net/$1/address"; }
test "$(actual_mac "$FABRIC0_IF")" = "${FABRIC0_MAC,,}" || {
  echo "$FABRIC0_IF does not have the configured permanent MAC" >&2
  exit 1
}
test "$(actual_mac "$FABRIC1_IF")" = "${FABRIC1_MAC,,}" || {
  echo "$FABRIC1_IF does not have the configured permanent MAC" >&2
  exit 1
}

default_interface=$(ip route show default | awk '
  NR == 1 { for (i = 1; i <= NF; i++) if ($i == "dev") print $(i + 1) }
')
for interface in "$FABRIC0_IF" "$FABRIC1_IF"; do
  test "$interface" != "$default_interface" || {
    echo "refusing to flush default-route interface: $interface" >&2
    exit 1
  }
done

if [ -n "${SSH_CONNECTION:-}" ]; then
  ssh_server_ip=$(awk '{print $3}' <<<"$SSH_CONNECTION")
  ssh_interface=$(ip -o -4 addr show | awk -v address="$ssh_server_ip" '
    $4 ~ ("^" address "/") { print $2; exit }
  ')
  for interface in "$FABRIC0_IF" "$FABRIC1_IF"; do
    test "$interface" != "$ssh_interface" || {
      echo "refusing to flush the interface carrying this SSH session" >&2
      exit 1
    }
  done
fi

CHECK_ROOT=$(mktemp -d)
cleanup() {
  case "$CHECK_ROOT" in
    /tmp/*) rm -rf -- "$CHECK_ROOT" ;;
    *) echo "refusing to remove unexpected check path: $CHECK_ROOT" >&2 ;;
  esac
}
trap cleanup EXIT
install -d -m 0755 "$CHECK_ROOT/etc/netplan"
"$ROOT/scripts/render-netplan.sh" "$CONFIG" > \
  "$CHECK_ROOT/etc/netplan/90-switchless-fabric.yaml"
chmod 0600 "$CHECK_ROOT/etc/netplan/90-switchless-fabric.yaml"
netplan generate --root-dir "$CHECK_ROOT"

install -m 0600 "$CHECK_ROOT/etc/netplan/90-switchless-fabric.yaml" \
  "$NETPLAN_FILE"

for interface in "$FABRIC0_IF" "$FABRIC1_IF"; do
  ip -4 addr flush dev "$interface" scope global
done
netplan apply

verify_address() {
  local interface=$1
  local expected=$2
  local actual
  actual=$(ip -o -4 addr show dev "$interface" scope global |
    awk '{print $4}')
  test "$actual" = "$expected" || {
    echo "$interface expected only $expected, found: ${actual:-none}" >&2
    return 1
  }
}

verify_address "$FABRIC0_IF" "$FABRIC0_ADDRESS"
verify_address "$FABRIC1_IF" "$FABRIC1_ADDRESS"

find_gid_index() {
  local interface=$1
  local address=${2%/*}
  show_gids | awk -v interface="$interface" -v address="$address" '
    $5 == address && $6 == "v2" && $7 == interface { print $3 }
  '
}

gid0=
gid1=
for _ in $(seq 1 20); do
  gid0=$(find_gid_index "$FABRIC0_IF" "$FABRIC0_ADDRESS")
  gid1=$(find_gid_index "$FABRIC1_IF" "$FABRIC1_ADDRESS")
  if [ -n "$gid0" ] && [ -n "$gid1" ]; then
    break
  fi
  sleep 1
done

test -n "$gid0" || { echo "no exact RoCEv2 GID for $FABRIC0_IF" >&2; exit 1; }
test -n "$gid1" || { echo "no exact RoCEv2 GID for $FABRIC1_IF" >&2; exit 1; }
test "$(wc -l <<<"$gid0")" -eq 1 || {
  echo "multiple exact RoCEv2 GIDs found for $FABRIC0_IF" >&2
  exit 1
}
test "$(wc -l <<<"$gid1")" -eq 1 || {
  echo "multiple exact RoCEv2 GIDs found for $FABRIC1_IF" >&2
  exit 1
}
test "$gid0" = "$gid1" || {
  echo "fabric GID indices differ: $FABRIC0_IF=$gid0, $FABRIC1_IF=$gid1" >&2
  exit 1
}

echo "fabric applied: $FABRIC0_IF=$FABRIC0_ADDRESS, $FABRIC1_IF=$FABRIC1_ADDRESS"
echo "legacy common GID index: $gid0"
echo "NCCL 2.21+ profiles should normally leave NCCL_IB_GID_INDEX unset"
