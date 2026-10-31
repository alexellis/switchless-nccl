#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Package and verify the pinned four-PF build; never install or qualify a runtime."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MARKERS = (
    'SWITCHLESS/HARDENED: skipping Tree transport setup',
    'SWITCHLESS/HARDENED: skipping PAT transport setup',
    'SWITCHLESS/FOUR-PF: listener contract:',
    'NET/IB ListenerRouting',
    'NET/IB RouteFinal',
)


def pins():
    values = dict(re.findall(r'^([A-Z0-9_]+)=([^\n]+)$',
                             (ROOT/'scripts/versions.sh').read_text(), re.M))
    profile = json.loads((ROOT/'profiles/dual-pf.json').read_text())
    return values, profile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def library_checks(library, version):
    require(library.is_file() and not library.is_symlink(), 'regular library required')
    require('AArch64' in command('readelf', '-h', str(library)), 'AArch64 library required')
    require('Library soname: [libnccl.so.2]' in command('readelf', '-d', str(library)),
            'libnccl.so.2 SONAME required')
    markers = command('strings', str(library))
    for marker in (f'NCCL version {version} compiled with CUDA 13.0', *MARKERS):
        require(marker in markers, 'missing four-PF binary marker: ' + marker)


def expected_payload(values, profile):
    return {
        f"libnccl.so.{values['NCCL_VERSION']}", 'LICENSE.NCCL.txt',
        'ThirdPartyNotices.NCCL.txt', 'LICENSE.project.txt', 'NOTICE',
        'THIRD_PARTY_NOTICES.md', 'PROVENANCE.md', 'docs/dual-pf.md',
        'examples/dual-pf.json', 'scripts/render-dual-pf-env.py',
        'profiles/dual-pf.json', 'source-receipt.json', 'build-receipt.json',
        'release-profile.json', *(p['path'] for p in profile['patches']),
    }


def verify_bundle(directory):
    values, profile = pins()
    expected = expected_payload(values, profile)
    entries = (directory/'SHA256SUMS').read_text().splitlines()
    checks = {}
    for line in entries:
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        require(match is not None, 'invalid checksum manifest')
        digest, name = match.groups()
        require(name in expected and name not in checks, 'unexpected or duplicate payload')
        checks[name] = digest
    require(set(checks) == expected, 'incomplete checksum manifest')
    symlinks = {'libnccl.so': 'libnccl.so.2',
                'libnccl.so.2': f"libnccl.so.{values['NCCL_VERSION']}"}
    actual = set()
    for path in directory.rglob('*'):
        name = path.relative_to(directory).as_posix()
        if path.is_symlink():
            require(name in symlinks and os.readlink(path) == symlinks[name],
                    'unexpected library symlink')
            actual.add(name)
        elif path.is_file():
            actual.add(name)
    require(actual == expected | {'SHA256SUMS'} | set(symlinks), 'unexpected package files')
    for name, digest in checks.items():
        require(not (directory/name).is_symlink() and sha(directory/name) == digest,
                'payload checksum mismatch: ' + name)
    require((directory/'profiles/dual-pf.json').read_bytes() ==
            (ROOT/'profiles/dual-pf.json').read_bytes(), 'four-PF profile pin mismatch')
    for patch in profile['patches']:
        require(sha(directory/patch['path']) == patch['sha256'], 'patch pin mismatch')
    require(sha(directory/'LICENSE.NCCL.txt') == values['NCCL_LICENSE_SHA256'],
            'NCCL license pin mismatch')
    require(sha(directory/'ThirdPartyNotices.NCCL.txt') == values['NCCL_NOTICES_SHA256'],
            'NCCL notices pin mismatch')
    source = json.loads((directory/'source-receipt.json').read_text())
    build = json.loads((directory/'build-receipt.json').read_text())
    metadata = json.loads((directory/'release-profile.json').read_text())
    library = directory/f"libnccl.so.{values['NCCL_VERSION']}"
    require(source.get('status') == 'SOURCE_TREE_VERIFIED_BUILD_UNRUN' and
            source.get('base') == profile['nccl_revision'] and
            source.get('tree') == profile['patched_tree'] and
            source.get('patches') == profile['patches'] and
            source.get('profile_sha256') == sha(ROOT/'profiles/dual-pf.json'),
            'source receipt pin mismatch')
    require(build.get('status') == 'PASS_NATIVE_COMPILE_ONLY' and
            build.get('runtime_qualified') is False and
            build.get('source_receipt') == source and
            build.get('cuda_image') == values['CUDA_IMAGE'] and
            build.get('library_sha256') == sha(library) and
            re.fullmatch(r'sha256:[0-9a-f]{64}', build.get('image_id', '')) and
            build.get('make_argv') == ['make', '-j2', 'src.build',
                                      'CUDA_HOME=/usr/local/cuda-13.0',
                                      'NVCC_GENCODE=-gencode=arch=compute_121,code=sm_121'],
            'build receipt mismatch')
    require(metadata == {
        'schema': 1, 'profile': 'four-pf', 'package_name': values['FOUR_PF_PACKAGE_NAME'],
        'source_tree': profile['patched_tree'], 'library_sha256': sha(library),
        'runtime_qualified': False, 'required_environment': profile['required_environment'],
        'deployment_environment': profile['deployment_environment'],
    }, 'release profile mismatch')
    library_checks(library, values['NCCL_VERSION'])
    return metadata


def package(build_directory, output):
    values, profile = pins()
    library = build_directory/f"source/build/lib/libnccl.so.{values['NCCL_VERSION']}"
    # Verify the retained source as well as the receipt; a stale index is insufficient.
    source = build_directory/'source'
    require(command('git', '-C', str(source), 'write-tree').strip() == profile['patched_tree'],
            'built source tree mismatch')
    command('git', '-C', str(source), 'diff', '--exit-code')
    output.mkdir(parents=True, exist_ok=True)
    asset = output/(values['FOUR_PF_PACKAGE_NAME']+'.tar.gz')
    require(not asset.exists() and not asset.is_symlink() and
            not Path(str(asset)+'.sha256').exists() and not Path(str(asset)+'.sha256').is_symlink(),
            'release asset already exists; choose fresh output')
    with tempfile.TemporaryDirectory(prefix='four-pf-package-') as tmp:
        directory = Path(tmp)/values['FOUR_PF_PACKAGE_NAME']
        directory.mkdir()
        copies = {
            library: f"libnccl.so.{values['NCCL_VERSION']}",
            source/'LICENSE.txt': 'LICENSE.NCCL.txt',
            source/'ThirdPartyNotices.txt': 'ThirdPartyNotices.NCCL.txt',
            ROOT/'LICENSE': 'LICENSE.project.txt',
            build_directory/'receipt.json': 'source-receipt.json',
            build_directory/'build-receipt.json': 'build-receipt.json',
        }
        for name in ('NOTICE', 'THIRD_PARTY_NOTICES.md', 'PROVENANCE.md',
                     'docs/dual-pf.md', 'examples/dual-pf.json',
                     'scripts/render-dual-pf-env.py', 'profiles/dual-pf.json',
                     *(p['path'] for p in profile['patches'])):
            copies[ROOT/name] = name
        for original, name in copies.items():
            target = directory/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            target.chmod(0o755 if name.startswith('libnccl') or name.startswith('scripts/') else 0o644)
        (directory/'libnccl.so.2').symlink_to(library.name)
        (directory/'libnccl.so').symlink_to('libnccl.so.2')
        metadata = {
            'schema': 1, 'profile': 'four-pf', 'package_name': values['FOUR_PF_PACKAGE_NAME'],
            'source_tree': profile['patched_tree'], 'library_sha256': sha(library),
            'runtime_qualified': False, 'required_environment': profile['required_environment'],
            'deployment_environment': profile['deployment_environment'],
        }
        (directory/'release-profile.json').write_text(json.dumps(metadata, indent=2)+'\n')
        payload = expected_payload(values, profile)
        (directory/'SHA256SUMS').write_text(''.join(f'{sha(directory/name)}  {name}\n'
                                                    for name in sorted(payload)))
        verify_bundle(directory)
        epoch = int(os.environ.get('SOURCE_DATE_EPOCH') or
                    command('git', '-C', str(ROOT), 'log', '-1', '--format=%ct').strip())
        # Canonical timestamps, ownership and ordering; publish only the completed archive.
        temporary = output/(asset.name+'.partial')
        with temporary.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for path in [directory, *sorted(directory.rglob('*'))]:
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(directory.parent).as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mtime = epoch
                    if info.isdir():
                        info.mode = 0o755
                    if info.isfile():
                        with path.open('rb') as contents:
                            archive.addfile(info, contents)
                    else:
                        archive.addfile(info)
        temporary.rename(asset)
        Path(str(asset)+'.sha256').write_text(f'{sha(asset)}  {asset.name}\n')
    return asset


def unpack(archive_path, destination):
    values, _ = pins()
    name = values['FOUR_PF_PACKAGE_NAME']
    directory = destination/name
    require(not directory.exists() and not directory.is_symlink(), 'fresh extraction path required')
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and '..' not in path.parts and path.parts and
                    path.parts[0] == name and member.name not in names, 'invalid archive member')
            names.add(member.name)
            require(member.isdir() or member.isfile() or member.issym(), 'unsupported archive member')
            if member.issym():
                expected = {name+'/libnccl.so': 'libnccl.so.2',
                            name+'/libnccl.so.2': f"libnccl.so.{values['NCCL_VERSION']}"}
                require(expected.get(member.name) == member.linkname, 'invalid archive symlink')
        # Write regular files first so an archive symlink cannot redirect extraction.
        for member in members:
            target = destination/member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
        for member in members:
            if member.issym():
                (destination/member.name).symlink_to(member.linkname)
    verify_bundle(directory)
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('package', 'unpack'):
        item = sub.add_parser(action)
        item.add_argument('source', type=Path)
        item.add_argument('destination', type=Path)
    sub.add_parser('verify').add_argument('source', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'verify':
            print(json.dumps(verify_bundle(args.source), indent=2))
        else:
            print((package if args.action == 'package' else unpack)(args.source, args.destination))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(2, f'four-PF release refused: {error}\n')


if __name__ == '__main__':
    main()
