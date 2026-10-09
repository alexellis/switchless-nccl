#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reconstruct the opt-in four-PF NCCL source from a local upstream checkout.

No network, build, installation, fabric mutation or service lifecycle actions.
Failures retain the incomplete output and a receipt; never retry automatically.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], env=ENV, stderr=subprocess.PIPE).decode().strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def inputs(root=ROOT):
    profile = json.loads((root / 'profiles/dual-pf.json').read_text())
    for entry in profile['patches']:
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root.resolve()) or sha(path) != entry['sha256']:
            raise ValueError('patch identity mismatch: ' + entry['path'])
    return profile


def prepare(source, output, root=ROOT):
    source, output = source.resolve(), output.absolute()
    profile = inputs(root)
    if output.exists() or output.is_symlink():
        raise ValueError('output must be fresh; retained runs cannot be overwritten')
    if not source.is_dir():
        raise ValueError('NCCL source must be an existing local Git checkout')
    if git(source, 'rev-parse', profile['nccl_revision'] + '^{tree}') != profile['base_tree']:
        raise ValueError('upstream base tree mismatch')
    output.mkdir(parents=True)
    target = output / 'source'
    try:
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout',
                        str(source), str(target)], env=ENV, check=True, capture_output=True)
        git(target, 'config', 'core.autocrlf', 'false')
        git(target, 'checkout', '--quiet', '--detach', profile['nccl_revision'])
        for entry in profile['patches']:
            patch = str((root / entry['path']).resolve())
            git(target, 'apply', '--check', patch)
            git(target, 'apply', '--index', patch)
        actual = git(target, 'write-tree')
        if actual != profile['patched_tree']:
            raise ValueError('patched source tree mismatch')
        # Detect worktree filters or filesystem changes outside the index.
        git(target, 'diff', '--exit-code')
        write(output / 'build-plan.json', {
            'status': 'UNRUN_REQUIRES_LINUX_AARCH64_CUDA13',
            'cwd': str(target),
            'argv': ['make', '-j4', 'src.build', 'CUDA_HOME=/usr/local/cuda-13.0',
                     'NVCC_GENCODE=-gencode=arch=compute_121,code=sm_121'],
            'library': 'build/lib/libnccl.so.2.30.7',
            'source_tree': actual,
            'required_environment': profile['required_environment'],
            'qualification': 'Rebuilt bytes require their own all-rank GPU and routing gates.'})
        receipt = {'status': 'SOURCE_TREE_VERIFIED_BUILD_UNRUN',
                   'base': profile['nccl_revision'], 'tree': actual,
                   'profile_sha256': sha(root / 'profiles/dual-pf.json'),
                   'patches': profile['patches']}
        write(output / 'receipt.json', receipt)
        return receipt
    except Exception as error:
        write(output / 'receipt.json', {'status': 'FAILED_NO_RETRY',
              'type': type(error).__name__, 'error': str(error),
              'stderr': getattr(error, 'stderr', b'').decode(errors='replace')})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nccl-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.nccl_source, args.output), indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
