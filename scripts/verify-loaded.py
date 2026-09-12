#!/usr/bin/env python3
"""Prove the expected NCCL library wins process-global resolution."""

import argparse
import ctypes
import os
from pathlib import Path


def nccl_mappings(pid: int) -> set[Path]:
    result: set[Path] = set()
    maps = Path(f"/proc/{pid}/maps").read_text(encoding="utf-8")
    for line in maps.splitlines():
        fields = line.split()
        if not fields:
            continue
        candidate = fields[-1].removesuffix(" (deleted)")
        if candidate.startswith("/") and "libnccl.so" in Path(candidate).name:
            result.add(Path(candidate).resolve())
    return result


class DlInfo(ctypes.Structure):
    """glibc dladdr result for an in-process NCCL symbol."""

    _fields_ = [
        ("dli_fname", ctypes.c_char_p),
        ("dli_fbase", ctypes.c_void_p),
        ("dli_sname", ctypes.c_char_p),
        ("dli_saddr", ctypes.c_void_p),
    ]


def resolved_nccl() -> Path:
    process = ctypes.CDLL(None)
    symbol = process.ncclGetVersion
    info = DlInfo()
    libdl = ctypes.CDLL("libdl.so.2")
    libdl.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(DlInfo)]
    libdl.dladdr.restype = ctypes.c_int
    address = ctypes.cast(symbol, ctypes.c_void_p)
    if libdl.dladdr(address, ctypes.byref(info)) == 0 or not info.dli_fname:
        raise RuntimeError("could not resolve process-global ncclGetVersion")
    return Path(info.dli_fname.decode()).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--pid", type=int, default=os.getpid())
    parser.add_argument(
        "--import-torch",
        action="store_true",
        help="import torch before checking this process",
    )
    args = parser.parse_args()

    expected = args.expected.resolve(strict=True)
    if args.import_torch:
        if args.pid != os.getpid():
            parser.error("--import-torch can only inspect the current process")
        __import__("torch")

    mappings = nccl_mappings(args.pid)
    if expected not in mappings:
        formatted = ", ".join(str(path) for path in sorted(mappings)) or "none"
        raise SystemExit(
            f"expected {expected} in PID {args.pid}; mapped NCCL: {formatted}"
        )

    if args.pid == os.getpid():
        resolved = resolved_nccl()
        if resolved != expected:
            raise SystemExit(
                f"process-global NCCL resolves to {resolved}; expected {expected}"
            )
        print(f"PID {args.pid} resolves process-global NCCL to {expected}")
    elif mappings != {expected}:
        formatted = ", ".join(str(path) for path in sorted(mappings))
        raise SystemExit(
            "external PID verification cannot resolve symbols and therefore "
            f"requires one NCCL mapping; found: {formatted}"
        )
    else:
        print(f"PID {args.pid} maps exactly {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
