#!/usr/bin/env python3
"""Fail unless a process maps exactly the expected NCCL library."""

import argparse
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
    if mappings != {expected}:
        formatted = ", ".join(str(path) for path in sorted(mappings)) or "none"
        raise SystemExit(
            f"expected exactly {expected} in PID {args.pid}; mapped NCCL: {formatted}"
        )

    print(f"PID {args.pid} maps exactly {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
