#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Native compile only. Never installs a library or accesses a GPU/fabric.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=versions.sh
source "$ROOT/scripts/versions.sh"
OUTPUT=${1:?usage: build-dual-pf-ci.sh FRESH_OUTPUT}
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || {
  echo 'native Linux aarch64 required' >&2; exit 2;
}
for command in docker git python3 file readelf sha256sum strings; do
  command -v "$command" >/dev/null
done
OUTPUT=$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).absolute())' "$OUTPUT")
for path in "$OUTPUT" "${OUTPUT}-upstream" "${OUTPUT}-upstream.log" \
  "${OUTPUT}-prepare.log" "${OUTPUT}-exit.txt"; do
  [[ ! -e "$path" && ! -L "$path" ]] || {
    echo 'fresh output, upstream and evidence paths required; inspect any previous failure first' >&2
    exit 2
  }
done
record_exit() {
  local result=$?
  printf 'exit_code=%s\n' "$result" > "${OUTPUT}-exit.txt"
  if [[ -d "$OUTPUT" && ! -L "$OUTPUT" ]]; then
    printf 'exit_code=%s\n' "$result" > "$OUTPUT/exit.txt"
  fi
}
trap record_exit EXIT
# Full checkout of the exact commit; the offline preparer must not lazy-fetch.
git init -q "${OUTPUT}-upstream" 2>&1 | tee "${OUTPUT}-upstream.log"
git -C "${OUTPUT}-upstream" fetch -q --depth=1 https://github.com/NVIDIA/nccl.git "$NCCL_COMMIT" \
  2>&1 | tee -a "${OUTPUT}-upstream.log"
git -C "${OUTPUT}-upstream" checkout -q --detach FETCH_HEAD \
  2>&1 | tee -a "${OUTPUT}-upstream.log"
python3 "$ROOT/scripts/prepare_dual_pf.py" --nccl-source "${OUTPUT}-upstream" --output "$OUTPUT" \
  2>&1 | tee "${OUTPUT}-prepare.log"
OUTPUT=$(cd "$OUTPUT" && pwd)
mkdir "$OUTPUT/licenses"
cp "$OUTPUT/source/LICENSE.txt" "$OUTPUT/source/ThirdPartyNotices.txt" "$OUTPUT/licenses/"
cp "$ROOT/LICENSE" "$ROOT/NOTICE" "$ROOT/THIRD_PARTY_NOTICES.md" "$OUTPUT/licenses/"
container="dual-pf-${GITHUB_RUN_ID:-local-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')}-${GITHUB_RUN_ATTEMPT:-1}"
printf '%s\n' "$container" > "$OUTPUT/container-name.txt"
# Retain the build container until the hosted VM expires. No --rm, cache pruning,
# privileged mode, devices, host networking, or NVIDIA runtime.
docker run -i --name "$container" --entrypoint bash \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$OUTPUT/source:/src" -w /src "$CUDA_IMAGE" -seu <<'CONTAINER' 2>&1 | tee "$OUTPUT/build.log"
    trap 'chown -R "$HOST_UID:$HOST_GID" /src/build 2>/dev/null || true' EXIT
    test "$(uname -m)" = aarch64
    test -x /usr/local/cuda-13.0/bin/nvcc
    /usr/local/cuda-13.0/bin/nvcc --version
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3
    make -j2 src.build CUDA_HOME=/usr/local/cuda-13.0 \
      NVCC_GENCODE="-gencode=arch=compute_121,code=sm_121"
CONTAINER
docker inspect "$container" --format '{{.Image}}' > "$OUTPUT/image-id.txt"
LIBRARY="$OUTPUT/source/build/lib/libnccl.so.$NCCL_VERSION"
file "$LIBRARY" | tee "$OUTPUT/elf.txt"
readelf -h "$LIBRARY" >> "$OUTPUT/elf.txt"
grep -F AArch64 "$OUTPUT/elf.txt" >/dev/null
readelf -d "$LIBRARY" > "$OUTPUT/dynamic.txt"
grep -F 'Library soname: [libnccl.so.2]' "$OUTPUT/dynamic.txt" >/dev/null
strings "$LIBRARY" > "$OUTPUT/strings.txt"
grep -F "NCCL version $NCCL_VERSION compiled with CUDA 13.0" "$OUTPUT/strings.txt" >/dev/null
grep -F 'SWITCHLESS/HARDENED: skipping Tree transport setup' "$OUTPUT/strings.txt" >/dev/null
grep -F 'SWITCHLESS/HARDENED: skipping PAT transport setup' "$OUTPUT/strings.txt" >/dev/null
sha256sum "$LIBRARY" > "$OUTPUT/library.sha256.txt"
python3 - "$OUTPUT" "$CUDA_IMAGE" <<'PYRECEIPT'
import hashlib, json, pathlib, sys
out = pathlib.Path(sys.argv[1])
source = json.loads((out / 'receipt.json').read_text())
library = out / 'source/build/lib/libnccl.so.2.30.7'
(out / 'build-receipt.json').write_text(json.dumps({
    'status': 'PASS_NATIVE_COMPILE_ONLY', 'runtime_qualified': False,
    'source_receipt': source, 'cuda_image': sys.argv[2],
    'image_id': (out / 'image-id.txt').read_text().strip(),
    'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
    'make_argv': ['make', '-j2', 'src.build', 'CUDA_HOME=/usr/local/cuda-13.0',
                  'NVCC_GENCODE=-gencode=arch=compute_121,code=sm_121'],
    'qualification': 'GPU collective correctness, routing and serving remain unrun.'
}, indent=2) + '\n')
PYRECEIPT
