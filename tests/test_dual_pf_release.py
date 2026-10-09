# SPDX-License-Identifier: Apache-2.0
"""CPU release plumbing tests. The AArch64 ELF fixture contains no NCCL code."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


release = module('dual_pf_release', 'scripts/package-dual-pf.py')
prep = module('dual_pf_prepare_release', 'scripts/prepare_dual_pf.py')


def installer_env(parent, assets):
    stubs = parent/'bin'; stubs.mkdir()
    curl = stubs/'curl'
    curl.write_text('#!/bin/sh\n'
                    'printf "%s\\n" "$3" >> "$CURL_CALLS"\n'
                    'cp "$TEST_ASSETS/${3##*/}" "$2"\n')
    curl.chmod(0o755)
    return dict(os.environ, PATH=str(stubs)+os.pathsep+os.environ['PATH'],
                TEST_ASSETS=str(assets), CURL_CALLS=str(parent/'urls'), HOME=str(parent/'home'))


def install(args, env):
    return subprocess.run(['bash', str(ROOT/'scripts/install-release.sh'), *map(str, args)],
                          env=env, capture_output=True, text=True)


def restricted_installer_env(parent, assets, missing=()):
    env = installer_env(parent, assets)
    # Expose only named tools so system PATH cannot satisfy a missing dependency.
    for name in ('bash', 'dirname', 'mv', 'readlink', 'sha256sum', 'tar', 'gzip', 'mktemp', 'rm', 'cp',
                 'mkdir', 'python3', 'readelf', 'strings'):
        if name not in missing:
            (parent/'bin'/name).symlink_to(shutil.which(name))
    env['PATH'] = str(parent/'bin')
    return env


def archive_bundle(bundle, assets):
    assets.mkdir(exist_ok=True)
    asset = assets/(bundle.name+'.tar.gz')
    with tarfile.open(asset, 'w:gz') as out:
        out.add(bundle, arcname=bundle.name)
    Path(str(asset)+'.sha256').write_text(f'{release.sha(asset)}  {asset.name}\n')
    return asset


@unittest.skipUnless(os.getenv('NCCL_SOURCE') and shutil.which('clang') and shutil.which('ld.lld'),
                     'pinned NCCL_SOURCE, clang and ld.lld required for CPU package fixtures')
class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.build = cls.root/'build'
        source_receipt = prep.prepare(Path(os.environ['NCCL_SOURCE']), cls.build)
        cls.values, cls.profile = release.pins()
        source = cls.build/'source'
        library = source/f"build/lib/libnccl.so.{cls.values['NCCL_VERSION']}"
        library.parent.mkdir(parents=True)
        fixture = cls.root/'fixture.c'
        fixture.write_text('const char markers[] = '+json.dumps('\n'.join([
            f"NCCL version {cls.values['NCCL_VERSION']} compiled with CUDA 13.0",
            *release.MARKERS]))+';\n')
        subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-shared',
                        '-nostdlib', '-Wl,-soname,libnccl.so.2', str(fixture), '-o', str(library)],
                       check=True, capture_output=True)
        cls.library = library
        (cls.build/'build-receipt.json').write_text(json.dumps({
            'status': 'PASS_NATIVE_COMPILE_ONLY', 'runtime_qualified': False,
            'source_receipt': source_receipt, 'cuda_image': cls.values['CUDA_IMAGE'],
            'image_id': 'sha256:'+'a'*64, 'library_sha256': release.sha(library),
            'make_argv': ['make', '-j2', 'src.build', 'CUDA_HOME=/usr/local/cuda-13.0',
                          'NVCC_GENCODE=-gencode=arch=compute_121,code=sm_121'],
            'qualification': 'CPU TEST FIXTURE: this library contains no NCCL implementation.',
        }))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def unpack_fixture(self, parent):
        asset = release.package(self.build, parent/'assets')
        stage = parent/'stage'
        stage.mkdir()
        return release.unpack(asset, stage)

    def test_complete_bundle_is_deterministic_and_preserves_licenses(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            first = release.package(self.build, parent/'one')
            second = release.package(self.build, parent/'two')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertNotEqual(first.name, self.values['PACKAGE_NAME']+'.tar.gz')
            stage = parent/'stage'; stage.mkdir()
            bundle = release.unpack(first, stage)
            metadata = release.verify_bundle(bundle)
            self.assertEqual(metadata['profile'], 'four-pf')
            self.assertIs(metadata['runtime_qualified'], False)
            self.assertEqual(metadata['source_tree'], self.profile['patched_tree'])
            self.assertEqual((bundle/'LICENSE.NCCL.txt').read_bytes(),
                             (self.build/'source/LICENSE.txt').read_bytes())
            self.assertEqual((bundle/'ThirdPartyNotices.NCCL.txt').read_bytes(),
                             (self.build/'source/ThirdPartyNotices.txt').read_bytes())
            for patch in self.profile['patches']:
                self.assertEqual(release.sha(bundle/patch['path']), patch['sha256'])
            before = first.read_bytes()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                release.package(self.build, parent/'one')
            self.assertEqual(first.read_bytes(), before)

    def test_corrupt_payload_wrong_profile_and_missing_patch_refused(self):
        for kind in ('library', 'profile', 'patch', 'symlink', 'soname-symlink',
                     'extra', 'receipt', 'source-receipt', 'marker'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                bundle = self.unpack_fixture(parent)
                if kind == 'library':
                    (bundle/self.library.name).write_bytes(b'corrupt')
                elif kind == 'profile':
                    (bundle/'release-profile.json').write_text('{"profile":"two-pf"}')
                    # Even a recomputed checksum does not make the wrong profile valid.
                    sums = bundle/'SHA256SUMS'
                    sums.write_text('\n'.join(
                        f"{release.sha(bundle/'release-profile.json')}  release-profile.json"
                        if line.endswith('  release-profile.json') else line
                        for line in sums.read_text().splitlines())+'\n')
                elif kind == 'patch':
                    (bundle/self.profile['patches'][-1]['path']).unlink()
                elif kind in ('symlink', 'soname-symlink'):
                    name = 'libnccl.so' if kind == 'symlink' else 'libnccl.so.2'
                    (bundle/name).unlink()
                    (bundle/name).symlink_to('/tmp/wrong-library')
                elif kind == 'extra':
                    (bundle/'untracked.txt').write_text('unexpected')
                elif kind == 'receipt':
                    receipt = bundle/'build-receipt.json'
                    data = json.loads(receipt.read_text())
                    data['runtime_qualified'] = True
                    receipt.write_text(json.dumps(data))
                elif kind == 'source-receipt':
                    receipt = bundle/'source-receipt.json'
                    data = json.loads(receipt.read_text())
                    data['base'] = '0'*40
                    receipt.write_text(json.dumps(data))
                else:
                    library = bundle/self.library.name
                    marker = release.MARKERS[0].encode()
                    self.assertIn(marker, library.read_bytes())
                    library.write_bytes(library.read_bytes().replace(marker, b'X'*len(marker)))
                    for name in ('build-receipt.json', 'release-profile.json'):
                        path = bundle/name
                        data = json.loads(path.read_text())
                        data['library_sha256'] = release.sha(library)
                        path.write_text(json.dumps(data))
                if kind in ('receipt', 'source-receipt', 'marker'):
                    sums = bundle/'SHA256SUMS'
                    names = [line.split('  ', 1)[1] for line in sums.read_text().splitlines()]
                    sums.write_text(''.join(f'{release.sha(bundle/name)}  {name}\n'
                                           for name in names))
                with self.assertRaises((ValueError, FileNotFoundError)):
                    release.verify_bundle(bundle)
                assets = parent/'corrupt-assets'
                archive_bundle(bundle, assets)
                destination = parent/'installed'
                result = install(['v0.1.0', destination], installer_env(parent, assets))
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(destination.exists())
                if kind == 'receipt':
                    self.assertIn('build receipt mismatch', result.stderr)
                elif kind == 'source-receipt':
                    self.assertIn('source receipt pin mismatch', result.stderr)
                elif kind == 'marker':
                    self.assertIn('missing four-PF binary marker', result.stderr)

    def test_failed_build_and_modified_source_produce_no_asset(self):
        receipt = self.build/'build-receipt.json'
        original = receipt.read_bytes()
        tracked = self.build/'source/src/transport/net_ib/connect.cc'
        source_bytes = tracked.read_bytes()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                data = json.loads(original)
                data['status'] = 'FAILED'
                receipt.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'build receipt'):
                    release.package(self.build, Path(tmp))
                self.assertFalse(list(Path(tmp).glob('*.tar.gz')))
            receipt.write_bytes(original)
            tracked.write_bytes(source_bytes+b'\n// changed after build\n')
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(subprocess.CalledProcessError):
                    release.package(self.build, Path(tmp))
                self.assertFalse(list(Path(tmp).glob('*.tar.gz')))
        finally:
            receipt.write_bytes(original)
            tracked.write_bytes(source_bytes)

    def test_default_installer_selects_four_pf_asset_in_requested_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            assets = parent/'assets'
            release.package(self.build, assets)
            env = installer_env(parent, assets)
            destination = parent/'installed'
            result = subprocess.run(['bash', str(ROOT/'scripts/install-release.sh'),
                '--repository', 'othexmr/switchless-nccl',
                'v0.1.0', str(destination)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(release.verify_bundle(destination)['profile'], 'four-pf')
            urls = (parent/'urls').read_text().splitlines()
            prefix = 'https://github.com/othexmr/switchless-nccl/releases/download/v0.1.0/'
            asset_name = self.values['FOUR_PF_PACKAGE_NAME']+'.tar.gz'
            self.assertEqual(urls, [prefix+asset_name, prefix+asset_name+'.sha256'])
            again = subprocess.run(['bash', str(ROOT/'scripts/install-release.sh'),
                'v0.1.0', str(destination)],
                env=env, capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)
            self.assertEqual((parent/'urls').read_text().splitlines(), urls)
            for args, destination in (
                (['v0.1.0', '--repository', 'othexmr/switchless-nccl'],
                 parent/'home/nccl-switchless-four-pf-v0.1.0'),
                (['v0.1.0', parent/'installed with spaces', '--profile', 'four-pf',
                  '--repository', 'othexmr/switchless-nccl'], parent/'installed with spaces'),
            ):
                with self.subTest(args=args):
                    (parent/'urls').unlink()
                    result = install(args, env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(release.verify_bundle(destination)['profile'], 'four-pf')
                    self.assertEqual((parent/'urls').read_text().splitlines(), urls)
            for kind in ('file', 'dangling-symlink'):
                destination = parent/kind
                if kind == 'file':
                    destination.write_text('existing')
                else:
                    destination.symlink_to(parent/'missing')
                result = install(['v0.1.0', destination], env)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual((parent/'urls').read_text().splitlines(), urls)
            # A valid download with a bad outer checksum must never install.
            (assets/(asset_name+'.sha256')).write_text('0'*64+'  '+asset_name+'\n')
            result = install(['v0.1.0', parent/'bad-checksum'], env)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((parent/'bad-checksum').exists())
            # Old releases contain only the two-PF archive; no fallback is allowed.
            missing = parent/'old-release'; missing.mkdir()
            (missing/(self.values['PACKAGE_NAME']+'.tar.gz')).write_bytes(b'two-PF asset')
            env['TEST_ASSETS'] = str(missing)
            (parent/'urls').unlink()
            result = install(['v0.0.1'], env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--profile two-pf', result.stderr)
            self.assertEqual((parent/'urls').read_text().splitlines(),
                ['https://github.com/alexellis/switchless-nccl/releases/download/v0.0.1/'+asset_name])
            self.assertFalse((parent/'home/nccl-switchless-four-pf-v0.0.1').exists())

    def test_archive_escape_is_refused_without_writing_outside_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            archive = parent/'bad.tar.gz'
            with tarfile.open(archive, 'w:gz') as out:
                item = tarfile.TarInfo(self.values['FOUR_PF_PACKAGE_NAME']+'/../../escape')
                item.size = 0
                out.addfile(item)
            stage = parent/'stage'; stage.mkdir()
            with self.assertRaisesRegex(ValueError, 'invalid archive member'):
                release.unpack(archive, stage)
            self.assertFalse((parent/'escape').exists())


class WorkflowTests(unittest.TestCase):
    def test_two_pf_installer_keeps_two_pf_asset_and_repository(self):
        values, _ = release.pins()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            bundle = parent/values['PACKAGE_NAME']; bundle.mkdir()
            library = bundle/f"libnccl.so.{values['NCCL_VERSION']}"
            library.write_bytes(b'CPU two-PF installer compatibility fixture')
            (bundle/'libnccl.so.2').symlink_to(library.name)
            (bundle/'libnccl.so').symlink_to('libnccl.so.2')
            (bundle/'SHA256SUMS').write_text(f'{release.sha(library)}  {library.name}\n')
            asset = archive_bundle(bundle, parent/'assets')
            env = installer_env(parent, asset.parent)
            destination = parent/'installed'
            result = subprocess.run(['bash', str(ROOT/'scripts/install-release.sh'),
                '--profile', 'two-pf', 'v0.0.1', str(destination)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((destination/library.name).read_bytes(), library.read_bytes())
            prefix = 'https://github.com/alexellis/switchless-nccl/releases/download/v0.0.1/'
            self.assertEqual((parent/'urls').read_text().splitlines(),
                             [prefix+asset.name, prefix+asset.name+'.sha256'])
            urls = [prefix+asset.name, prefix+asset.name+'.sha256']
            # The legacy installer must still work without any four-PF-only tool.
            restricted = parent/'restricted'; restricted.mkdir()
            restricted_env = restricted_installer_env(
                restricted, asset.parent, missing=('python3', 'readelf', 'strings'))
            destination = restricted/'installed'
            result = install(['--profile', 'two-pf', 'v0.0.1', destination], restricted_env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((destination/library.name).read_bytes(), library.read_bytes())
            self.assertEqual((restricted/'urls').read_text().splitlines(), urls)
            for args, destination in (
                (['v0.0.1', '--profile', 'two-pf'], parent/'home/nccl-switchless-v0.0.1'),
                (['v0.0.1', parent/'installed with spaces', '--profile', 'two-pf'],
                 parent/'installed with spaces'),
            ):
                with self.subTest(args=args):
                    (parent/'urls').unlink()
                    result = install(args, env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((destination/library.name).read_bytes(), library.read_bytes())
                    self.assertEqual((parent/'urls').read_text().splitlines(), urls)
            for kind in ('directory', 'file', 'dangling-symlink'):
                destination = parent/('existing-'+kind)
                if kind == 'directory':
                    destination.mkdir()
                elif kind == 'file':
                    destination.write_text('existing')
                else:
                    destination.symlink_to(parent/'missing')
                result = install(['v0.0.1', destination, '--profile', 'two-pf'], env)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual((parent/'urls').read_text().splitlines(), urls)
            for kind in ('archive-checksum', 'payload-checksum', 'symlink', 'soname-symlink'):
                with self.subTest(kind=kind):
                    if kind == 'payload-checksum':
                        library.write_bytes(b'corrupt')
                    elif kind in ('symlink', 'soname-symlink'):
                        # Restore the other link so each refusal tests only one bad link.
                        (bundle/'libnccl.so').unlink()
                        (bundle/'libnccl.so').symlink_to('libnccl.so.2')
                        name = 'libnccl.so' if kind == 'symlink' else 'libnccl.so.2'
                        (bundle/name).unlink()
                        (bundle/name).symlink_to('/tmp/wrong-library')
                        library.write_bytes(b'CPU two-PF installer compatibility fixture')
                    asset = archive_bundle(bundle, asset.parent)
                    if kind == 'archive-checksum':
                        Path(str(asset)+'.sha256').write_text('0'*64+'  '+asset.name+'\n')
                    destination = parent/('bad-'+kind)
                    result = install(['--profile', 'two-pf', 'v0.0.1', destination], env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(destination.exists())

    def test_one_publish_job_uploads_only_after_both_packages(self):
        workflow = (ROOT/'.github/workflows/publish.yml').read_text()
        self.assertEqual(workflow.count('  publish:\n'), 1)
        package = workflow.index('package-dual-pf.py package')
        upload = workflow.index('name: Upload release assets')
        self.assertLess(workflow.index('package-nccl.sh'), package)
        self.assertLess(package, upload)
        self.assertNotIn('continue-on-error', workflow)
        self.assertNotIn('if: always()', workflow[upload:])
        self.assertIn('asset_paths: \'["./bin/*"]\'', workflow)

    def test_invalid_input_and_missing_dependencies_refused_before_download(self):
        cases = (['--profile', 'unknown', 'v0.1.0'],
                 ['v0.1.0', '--profile', 'unknown'],
                 ['--repository', 'owner/repo/extra', 'v0.1.0'],
                 ['v0.1.0', '--repository', 'owner/repo/extra'],
                 ['v0.1.0', '--profile'], ['v0.1.0', '--repository'],
                 ['--profile', '--repository', 'v0.1.0'],
                 ['v0.1.0', '--profile', ''], ['v0.1.0', '--unknown'],
                 [], ['v0.1.0', 'destination', 'extra'])
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            env = installer_env(parent, parent/'no-assets')
            for args in cases:
                with self.subTest(args=args):
                    result = install(args, env)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertFalse((parent/'urls').exists(), result.stderr)
        for missing in ('python3', 'readelf', 'strings', 'old-python'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                omitted = 'python3' if missing == 'old-python' else missing
                env = restricted_installer_env(parent, parent/'no-assets', missing=(omitted,))
                if missing == 'old-python':
                    python = parent/'bin/python3'
                    python.write_text('#!/bin/sh\nexit 1\n')
                    python.chmod(0o755)
                    error = 'four-PF installation requires Python 3.11 or newer'
                else:
                    error = 'missing required command: '+missing
                destination = parent/'installed'
                result = install(['v0.1.0', destination], env)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(error, result.stderr)
                self.assertFalse((parent/'urls').exists(), result.stderr)
                self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
