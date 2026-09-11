# Fabric runbook

Each Spark in a four-node cycle has two fabric NICs, one for each direct
neighbour. Give each physical link its own IPv4 `/24`. Keep rendezvous and NCCL
bootstrap on the ordinary management LAN.

## Why stale addresses break GID selection

The mlx5 driver creates GID table entries as addresses appear. A node converted
from a TP2 setup can retain an older global address, so its intended RoCEv2 GID
lands above index 3. NCCL accepts one rank-wide `NCCL_IB_GID_INDEX`; if the two
ports settle on different indices, selecting a correct cable becomes brittle.

Netplan describes the desired persistent state, but it does not guarantee that
manually added live addresses disappear in the order needed to normalise the
GID table. NCCL 2.21 and later can select the address dynamically, but stale
addresses still make that selection and listener advertisement ambiguous.
`fabric-apply.sh` therefore performs one bounded reset:

1. render and validate the complete Netplan file without touching live state;
2. prove each named interface has the expected permanent MAC;
3. refuse the default-route and current SSH interfaces;
4. flush global IPv4 addresses only from the two fabric interfaces;
5. apply Netplan; and
6. wait for exactly the configured IPv4 RoCEv2 GID on each port.

It prints the common legacy index and fails if the two indices differ. New
NCCL 2.30.7 profiles should normally leave `NCCL_IB_GID_INDEX` unset, per
NVIDIA's guidance, and select IPv4 RoCEv2 dynamically. On the validated DGX
Spark layout, link-local v1/v2 occupy
indices 0 and 1, IPv4 RoCEv1 occupies 2, and IPv4 RoCEv2 occupies 3. The script
discovers and verifies that result instead of blindly assuming it.

## Apply per node

Copy and edit the example outside the checkout:

```bash
cp examples/fabric.env ./fabric.env
sudo ./scripts/fabric-apply.sh ./fabric.env
```

Run it locally on each node. Do not use one node's MAC addresses or fabric
addresses on another. The generated file uses NetworkManager, disables DHCP,
IPv6 router advertisements, and link-local addressing on the fabric ports,
sets MTU 9000, and matches each port by its permanent MAC before restoring its
normal interface name.

After applying all four nodes, verify every directly cabled peer with a jumbo
ping, then run a real NCCL collective. If Docker is used for routed traffic,
restore and verify the deployment's `DOCKER-USER` forwarding rules after any
Docker restart; those policy rules are intentionally outside this repository.

## Safety boundary

The apply command changes network state and requires root. Its scope is the two
interfaces named in `fabric.env` and one explicit Netplan file. It will not
flush the default-route interface or the interface carrying the current SSH
connection. Review the rendered file before first use:

```bash
./scripts/render-netplan.sh ./fabric.env
```
