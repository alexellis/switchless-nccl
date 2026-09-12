#!/usr/bin/env python3
"""Value-check the switchless four-rank NCCL contract without model weights."""

import hashlib
import ctypes
import os
from pathlib import Path
import time

import torch
import torch.distributed as dist


def mapped_nccl() -> set[str]:
    paths: set[str] = set()
    for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
        path = line.split()[-1]
        if "/" in path and "libnccl.so" in path:
            paths.add(str(Path(path).resolve()))
    return paths


class DlInfo(ctypes.Structure):
    """glibc dladdr result used to prove which NCCL wins interposition."""

    _fields_ = [
        ("dli_fname", ctypes.c_char_p),
        ("dli_fbase", ctypes.c_void_p),
        ("dli_sname", ctypes.c_char_p),
        ("dli_saddr", ctypes.c_void_p),
    ]


def resolved_nccl() -> str:
    process = ctypes.CDLL(None)
    symbol = process.ncclGetVersion
    info = DlInfo()
    libdl = ctypes.CDLL("libdl.so.2")
    libdl.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(DlInfo)]
    libdl.dladdr.restype = ctypes.c_int
    address = ctypes.cast(symbol, ctypes.c_void_p)
    if libdl.dladdr(address, ctypes.byref(info)) == 0 or not info.dli_fname:
        raise RuntimeError("could not resolve process-global ncclGetVersion")
    return str(Path(info.dli_fname.decode()).resolve())


def synchronised_ms(operation) -> float:
    torch.cuda.synchronize()
    dist.barrier()
    started = time.perf_counter()
    operation()
    torch.cuda.synchronize()
    dist.barrier()
    return (time.perf_counter() - started) * 1000


def require_all(tensor: torch.Tensor, expected: float, label: str) -> None:
    if not torch.all(tensor == expected):
        actual = tensor.flatten()[0].item()
        raise RuntimeError(f"{label}: expected {expected}, got {actual}")


def main() -> None:
    rank = int(os.environ["RANK"])
    world = int(os.environ.get("WORLD_SIZE", "4"))
    expected_path = str(Path(os.environ["EXPECTED_NCCL_PATH"]).resolve())
    expected_hash = os.environ["EXPECTED_NCCL_SHA256"]

    torch.cuda.set_device(0)
    dist.init_process_group("nccl", rank=rank, world_size=world)

    mapped = mapped_nccl()
    if expected_path not in mapped:
        raise RuntimeError(
            f"rank {rank}: candidate NCCL is not mapped: {sorted(mapped)}"
        )
    resolved = resolved_nccl()
    if resolved != expected_path:
        raise RuntimeError(
            f"rank {rank}: process-global NCCL resolves to {resolved}, "
            f"expected {expected_path}; mapped={sorted(mapped)}"
        )
    actual_hash = hashlib.sha256(Path(expected_path).read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError(
            f"rank {rank}: NCCL hash {actual_hash} != expected {expected_hash}"
        )

    total = world * (world + 1) / 2
    sizes = [int(value) for value in os.environ.get("SMOKE_BYTES", "1048576,67108864").split(",")]
    for size in sizes:
        count = size // torch.tensor([], dtype=torch.float32).element_size()

        value = torch.full((count,), rank + 1, device="cuda", dtype=torch.float32)
        elapsed = synchronised_ms(lambda: dist.all_reduce(value))
        require_all(value, total, f"all_reduce/{size}")

        source = torch.full((count,), rank + 1, device="cuda", dtype=torch.float32)
        gathered = torch.empty((world * count,), device="cuda", dtype=torch.float32)
        gather_ms = synchronised_ms(lambda: dist.all_gather_into_tensor(gathered, source))
        for peer in range(world):
            require_all(
                gathered[peer * count : (peer + 1) * count],
                peer + 1,
                f"all_gather/{size}/peer-{peer}",
            )

        scatter_input = torch.full(
            (world * count,), rank + 1, device="cuda", dtype=torch.float32
        )
        scattered = torch.empty((count,), device="cuda", dtype=torch.float32)
        scatter_ms = synchronised_ms(
            lambda: dist.reduce_scatter_tensor(scattered, scatter_input)
        )
        require_all(scattered, total, f"reduce_scatter/{size}")

        broadcast = torch.full(
            (count,), 12345 if rank == 0 else 0, device="cuda", dtype=torch.float32
        )
        broadcast_ms = synchronised_ms(lambda: dist.broadcast(broadcast, src=0))
        require_all(broadcast, 12345, f"broadcast/{size}")

        if rank == 0:
            print(
                f"size={size} all_reduce_ms={elapsed:.3f} "
                f"all_gather_ms={gather_ms:.3f} "
                f"reduce_scatter_ms={scatter_ms:.3f} "
                f"broadcast_ms={broadcast_ms:.3f}",
                flush=True,
            )

    graph_tensor = torch.ones((262144,), device="cuda", dtype=torch.float32)
    dist.all_reduce(graph_tensor)
    graph_tensor.fill_(1)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        dist.all_reduce(graph_tensor)
    graph_tensor.fill_(1)
    graph.replay()
    torch.cuda.synchronize()
    require_all(graph_tensor, world, "cuda_graph/all_reduce")
    del graph
    del graph_tensor
    torch.cuda.synchronize()

    dist.barrier()
    if rank == 0:
        print(
            f"PASS ranks={world} nccl_sha256={actual_hash} "
            f"resolved_nccl={resolved} cuda_graph=all_reduce",
            flush=True,
        )
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
