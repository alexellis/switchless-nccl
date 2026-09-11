#!/usr/bin/env bash
# Render a two-port DGX Spark fabric Netplan from a per-node environment file.
set -euo pipefail

CONFIG=${1:?usage: render-netplan.sh CONFIG}
test -f "$CONFIG" || { echo "config not found: $CONFIG" >&2; exit 1; }

# shellcheck disable=SC1090
source "$CONFIG"

for name in \
  FABRIC0_IF FABRIC0_MAC FABRIC0_ADDRESS \
  FABRIC1_IF FABRIC1_MAC FABRIC1_ADDRESS; do
  test -n "${!name:-}" || { echo "missing $name" >&2; exit 1; }
done

for interface in "$FABRIC0_IF" "$FABRIC1_IF"; do
  case "$interface" in
    *[!A-Za-z0-9_.:-]*) echo "invalid interface name: $interface" >&2; exit 1 ;;
  esac
done
for mac in "$FABRIC0_MAC" "$FABRIC1_MAC"; do
  case "$mac" in
    [0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]) ;;
    *) echo "invalid MAC address: $mac" >&2; exit 1 ;;
  esac
done

python3 - "$FABRIC0_ADDRESS" "$FABRIC1_ADDRESS" <<'PY'
import ipaddress
import sys

addresses = [ipaddress.ip_interface(value) for value in sys.argv[1:]]
if any(item.version != 4 for item in addresses):
    raise SystemExit("fabric addresses must be IPv4")
if addresses[0].network == addresses[1].network:
    raise SystemExit("fabric interfaces must use different subnets")
PY

test "$FABRIC0_IF" != "$FABRIC1_IF" || {
  echo "fabric interfaces must be different" >&2
  exit 1
}
test "${FABRIC0_MAC,,}" != "${FABRIC1_MAC,,}" || {
  echo "fabric MAC addresses must be different" >&2
  exit 1
}

cat <<EOF
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    switchless0:
      match:
        macaddress: "${FABRIC0_MAC,,}"
      set-name: "$FABRIC0_IF"
      addresses:
        - "$FABRIC0_ADDRESS"
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      mtu: 9000
      optional: true
      networkmanager:
        passthrough:
          connection.autoconnect: "true"
          ipv4.never-default: "true"
          ipv6.never-default: "true"
    switchless1:
      match:
        macaddress: "${FABRIC1_MAC,,}"
      set-name: "$FABRIC1_IF"
      addresses:
        - "$FABRIC1_ADDRESS"
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      mtu: 9000
      optional: true
      networkmanager:
        passthrough:
          connection.autoconnect: "true"
          ipv4.never-default: "true"
          ipv6.never-default: "true"
EOF
