#!/usr/bin/env bash
# Run the weight-free collective gate concurrently on a four-Spark cycle.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONFIG=${1:?usage: live-collective.sh CONFIG CANDIDATE_DIR}
CANDIDATE_DIR=${2:?usage: live-collective.sh CONFIG CANDIDATE_DIR}

# shellcheck disable=SC1090
source "$CONFIG"
: "${SSH_USER:?missing SSH_USER}"
: "${MASTER_ADDR:?missing MASTER_ADDR}"
: "${IMAGE:?missing IMAGE}"
: "${IB_HCA:?missing IB_HCA}"
: "${GID_INDEX:?missing GID_INDEX}"
: "${MGMT_IF:?missing MGMT_IF}"
test "${#NODES[@]}" -eq 4

library="$CANDIDATE_DIR/libnccl.so.2.30.7"
expected=$(ssh -o BatchMode=yes "$SSH_USER@${NODES[0]}" "sha256sum '$library' | cut -d ' ' -f1")
for node in "${NODES[@]}"; do
  actual=$(ssh -o BatchMode=yes "$SSH_USER@$node" "sha256sum '$library' | cut -d ' ' -f1")
  if [ "$actual" != "$expected" ]; then
    echo "$node has NCCL $actual, expected $expected" >&2
    exit 1
  fi
  scp -q "$ROOT/scripts/collective-smoke.py" "$SSH_USER@$node:switchless-nccl-collective-smoke.py"
done

log_dir=$(mktemp -d)
pids=()
for rank in 0 1 2 3; do
  node=${NODES[$rank]}
  ssh -o BatchMode=yes "$SSH_USER@$node" \
    "docker rm -f switchless-nccl-smoke >/dev/null 2>&1 || true; timeout 180 docker run --rm --name switchless-nccl-smoke --entrypoint python3 --gpus all --network host --ipc host --cap-add IPC_LOCK --ulimit memlock=-1:-1 --device /dev/infiniband:/dev/infiniband -v '$CANDIDATE_DIR:/opt/switchless-nccl:ro' -v /home/alex/switchless-nccl-collective-smoke.py:/smoke.py:ro -e LD_PRELOAD=/opt/switchless-nccl/libnccl.so.2.30.7 -e VLLM_NCCL_SO_PATH=/opt/switchless-nccl/libnccl.so.2.30.7 -e EXPECTED_NCCL_PATH=/opt/switchless-nccl/libnccl.so.2.30.7 -e EXPECTED_NCCL_SHA256='$expected' -e RANK='$rank' -e WORLD_SIZE=4 -e MASTER_ADDR='$MASTER_ADDR' -e MASTER_PORT='${MASTER_PORT:-29630}' -e NCCL_SKIP_TREE_CONNECT=1 -e NCCL_SWITCHLESS_RING_ONLY=1 -e NCCL_ALGO=Ring -e NCCL_NET=IB -e NCCL_IB_DISABLE=0 -e NCCL_IB_HCA='$IB_HCA' -e NCCL_IB_GID_INDEX='$GID_INDEX' -e NCCL_IB_ROCE_VERSION_NUM=2 -e NCCL_IB_ADDR_FAMILY=AF_INET -e NCCL_IB_SUBNET_PREFIX_LEN=24 -e NCCL_IB_SUBNET_AWARE_ROUTING=1 -e NCCL_IB_MERGE_NICS=0 -e NCCL_CROSS_NIC=1 -e NCCL_SOCKET_IFNAME='$MGMT_IF' -e GLOO_SOCKET_IFNAME='$MGMT_IF' -e NCCL_CUMEM_ENABLE=0 -e NCCL_DEBUG=INFO -e NCCL_DEBUG_SUBSYS=INIT,NET '$IMAGE' /smoke.py" \
    >"$log_dir/rank-$rank.log" 2>&1 &
  pids+=("$!")
done

failed=0
for rank in 0 1 2 3; do
  rank_failed=0
  if ! wait "${pids[$rank]}"; then
    rank_failed=1
    failed=1
  fi
  echo "== rank $rank / ${NODES[$rank]} =="
  if [ "$rank_failed" -eq 0 ] && ! grep -Eq \
    'SWITCHLESS|Tree transport setup disabled' "$log_dir/rank-$rank.log"; then
    echo "candidate-specific switchless diagnostic was not observed" >&2
    rank_failed=1
    failed=1
  fi
  if [ "$rank_failed" -eq 0 ]; then
    grep -E \
      'SWITCHLESS|Connected all rings|Init COMPLETE|size=|PASS ranks=' \
      "$log_dir/rank-$rank.log" || true
  else
    tail -n 80 "$log_dir/rank-$rank.log"
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "collective smoke failed; logs retained at $log_dir" >&2
  exit 1
fi

echo "collective smoke passed; logs retained at $log_dir"
