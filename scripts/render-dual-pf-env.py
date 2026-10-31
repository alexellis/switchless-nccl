#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render a validated, deployment-owned four-PF configuration; no host actions."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r'[A-Za-z0-9_.-]+\Z')


def render(config):
    expected = {'hcas', 'fabric_cidr', 'fabric_addresses', 'socket_ifname'}
    if not isinstance(config, dict) or set(config) != expected:
        raise ValueError('configuration requires exactly: ' + ', '.join(sorted(expected)))
    hcas = config['hcas']
    if not isinstance(hcas, list) or len(hcas) != 4 or any(
            not isinstance(name, str) or not NAME.fullmatch(name) for name in hcas):
        raise ValueError('hcas must contain four exact device names without ports or selectors')
    if len(set(hcas)) != 4:
        raise ValueError('hcas must be distinct')
    interface = config['socket_ifname']
    if not isinstance(interface, str) or not NAME.fullmatch(interface) or len(interface) > 15:
        raise ValueError('socket_ifname must be one interface name, at most 15 characters')
    if not isinstance(config['fabric_cidr'], str):
        raise ValueError('fabric_cidr must be an IPv4 CIDR string')
    network = ipaddress.IPv4Network(config['fabric_cidr'], strict=True)
    raw_addresses = config['fabric_addresses']
    if (not isinstance(raw_addresses, list) or len(raw_addresses) != 4
            or any(not isinstance(value, str) for value in raw_addresses)):
        raise ValueError('fabric_addresses must contain four IPv4 addresses, one per HCA')
    addresses = [ipaddress.IPv4Address(value) for value in raw_addresses]
    if len(set(addresses)) != 4:
        raise ValueError('fabric addresses must be distinct')
    subnets = {}
    for address in addresses:
        octets = address.packed
        if (octets[0] in (0, 127) or octets[0] >= 224 or octets[3] in (0, 255)
                or address not in network):
            raise ValueError('every address must be a unicast /24 host inside fabric_cidr')
        subnet = ipaddress.IPv4Network(f'{address}/24', strict=False)
        subnets[subnet] = subnets.get(subnet, 0) + 1
    # Per-cable layout: two /24s, one per cable, two PFs each.
    # Per-function layout: four /24s, one per PF (NVIDIA p0-to-p1 playbook style).
    if sorted(subnets.values()) not in ([2, 2], [1, 1, 1, 1]):
        raise ValueError('four PFs need two cable /24s with two addresses each, '
                         'or four distinct per-function /24s')
    profile = json.loads((ROOT/'profiles/dual-pf.json').read_text())
    env = dict(profile['required_environment'])
    env.update(NCCL_IB_HCA='='+','.join(hcas), NCCL_IB_ADDR_RANGE=str(network),
               NCCL_SOCKET_IFNAME='='+interface, GLOO_SOCKET_IFNAME=interface)
    return 'unset NCCL_IB_GID_INDEX\n' + ''.join(f'export {name}={shlex.quote(value)}\n' for name, value in sorted(env.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    try:
        result = render(json.loads(args.config.read_text()))
    except (ValueError, TypeError, OSError) as error:
        parser.exit(2, str(error)+'\n')
    # Emit nothing until every field has passed validation.
    sys.stdout.write(result)


if __name__ == '__main__':
    main()
