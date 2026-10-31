# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_dual_pf', ROOT/'scripts/prepare_dual_pf.py')
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)
env_spec = importlib.util.spec_from_file_location('dual_pf_env', ROOT/'scripts/render-dual-pf-env.py')
env_renderer = importlib.util.module_from_spec(env_spec)
env_spec.loader.exec_module(env_renderer)


class InputTests(unittest.TestCase):
    def test_patch_hashes(self):
        self.assertEqual(len(prep.inputs()['patches']), 4)

    def test_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT/'profiles', root/'profiles')
            shutil.copytree(ROOT/'patches', root/'patches')
            (root/'patches/nccl-2.30.7-dual-pf.patch').write_text('bad')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                prep.inputs(root)

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'fresh'):
                prep.prepare(Path(tmp), Path(tmp))

    @unittest.skipUnless(os.getenv('NCCL_SOURCE'), 'set NCCL_SOURCE to a local pinned NCCL checkout')
    def test_real_patch_stack_and_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'prepared'
            result = prep.prepare(Path(os.environ['NCCL_SOURCE']), output)
            self.assertEqual(result['tree'], prep.inputs()['patched_tree'])
            source = (output/'source/src/transport/net_ib/connect.cc').read_text()
            self.assertEqual(source.count('// Modified by switchless-nccl: bound switchless listener GID selection.'), 1)
            # Compile the real shared switchless predicate with stub parameters.
            # This also catches future drift in alias handling without a CUDA build.
            generic = (output/'source/src/transport/generic.cc').read_text()
            predicate = re.search(r'bool ncclSwitchlessRingOnly\(\) \{[^}]+\}', generic).group()
            self.assertIn('const bool strict = ncclSwitchlessRingOnly();', source)
            self.assertIn('switchlessListenerDevices(strict, extended, dev, ncclNMergedIbDevs)', source)
            alias = Path(tmp)/'alias.cc'
            alias.write_text('#include <cassert>\n#include "switchless_listener_contract.h"\n'
                'static int ring, legacy;\n'
                'int ncclParamSwitchlessRingOnly() { return ring; }\n'
                'int ncclParamSkipTreeConnect() { return legacy; }\n' + predicate + '\n'
                'int main() {\n'
                ' for (ring=0; ring<2; ++ring) for (legacy=0; legacy<2; ++legacy) {\n'
                '  const bool strict = ncclSwitchlessRingOnly();\n'
                '  assert(strict == (ring || legacy));\n'
                '  auto devices = switchlessListenerDevices(strict, false, 2, 4);\n'
                '  assert(devices.begin == (strict ? 0 : 2));\n'
                '  assert(devices.end == (strict ? 4 : 3));\n'
                '  unsigned char gids[4][16] = {}; char roots[4][11] = {};\n'
                '  if (strict) assert(switchlessValidateListener(gids, roots, 4, true));\n'
                ' }\n}\n')
            for test, path, extra in [
                ('codec', output/'source/tests/routing_handle/compat.cc', []),
                ('alias', alias, ['-I'+str(output/'source/src/transport/net_ib')]),
                ('listener', ROOT/'tests/dual_pf_listener.cc', ['-I'+str(output/'source/src/transport/net_ib')])]:
                exe = Path(tmp)/test
                subprocess.run(['c++', '-std=c++11', '-O2', '-Wall', '-Wextra', '-Werror',
                                *extra, str(path), '-o', str(exe)], check=True)
                subprocess.run([str(exe)], check=True)
            build = json.loads((output/'build-plan.json').read_text())
            self.assertTrue(build['status'].startswith('UNRUN'))
            self.assertEqual(build['argv'][0], 'make')


class ConfigurationTests(unittest.TestCase):
    @staticmethod
    def config():
        return dict(hcas=['mlx5_0', 'mlx5_1', 'mlx5_2', 'mlx5_3'],
                    fabric_cidr='192.0.2.0/23',
                    fabric_addresses=['192.0.2.1', '192.0.2.2', '192.0.3.1', '192.0.3.2'],
                    socket_ifname='eth0')

    def test_portable_output_and_exact_hca_selection(self):
        text = env_renderer.render(self.config())
        # Check shell semantics without loading a library or contacting a host.
        result = subprocess.run(['bash', '-c', 'export NCCL_IB_GID_INDEX=3\n' + text +
            'printf "%s\\n" "$NCCL_IB_HCA" "$NCCL_IB_ADDR_RANGE" "$NCCL_SOCKET_IFNAME" '
            '"$GLOO_SOCKET_IFNAME" "$NCCL_IB_EXTENDED_IPV4_GIDS" "${NCCL_IB_GID_INDEX-unset}"'],
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(),
                         ['=mlx5_0,mlx5_1,mlx5_2,mlx5_3', '192.0.2.0/23', '=eth0', 'eth0', '1', 'unset'])

    def test_per_function_layout_accepted(self):
        config = dict(self.config(), fabric_cidr='192.0.0.0/22',
                      fabric_addresses=['192.0.0.1', '192.0.1.1', '192.0.2.1', '192.0.3.1'])
        text = env_renderer.render(config)
        self.assertIn("export NCCL_IB_ADDR_RANGE=192.0.0.0/22\n", text)
        self.assertIn("export NCCL_IB_HCA==mlx5_0,mlx5_1,mlx5_2,mlx5_3\n", text)

    def test_invalid_sites_refused(self):
        variants = [
            {'hcas': ['mlx5_0']*4}, {'hcas': ['mlx5_0', 'mlx5_1', 'mlx5_2', 'x;touch /tmp/x']},
            {'socket_ifname': 'eth0,eth1'}, {'socket_ifname': '0123456789012345'},
            {'fabric_cidr': '192.0.2.1/23'}, {'fabric_cidr': '::/0'},
            {'fabric_cidr': '192.0.2.0/24'},
            {'fabric_addresses': ['192.0.2.1']*4},
            {'fabric_addresses': ['192.0.2.1', '192.0.2.2', '192.0.2.3', '192.0.2.4']},
            {'fabric_cidr': '192.0.0.0/22',
             'fabric_addresses': ['192.0.0.1', '192.0.1.1', '192.0.1.2', '192.0.2.1']},
            {'fabric_addresses': ['192.0.2.1', '192.0.2.2', '192.0.3.1', '192.0.3.255']},
            {'extra': 'unsupported'},
        ]
        for update in variants:
            with self.subTest(update=update), self.assertRaises((ValueError, TypeError)):
                env_renderer.render(dict(self.config(), **update))

    def test_cli_invalid_config_has_no_partial_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.json'
            path.write_text(json.dumps(dict(self.config(), socket_ifname='bad;command')))
            result = subprocess.run(['python3', str(ROOT/'scripts/render-dual-pf-env.py'), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')

class HostedBuildTests(unittest.TestCase):
    def test_early_failures_retain_evidence_and_stop(self):
        """No Docker call or subsequent checkout after a failed fetch/prepare."""
        for stage, code in [('fetch', 41), ('prepare', 42)]:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                env = self.early_fixture(root, stage)
                out = root/'build'
                result = subprocess.run(['bash', str(root/'scripts/build-dual-pf-ci.sh'), str(out)],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual((root/'build-exit.txt').read_text(), f'exit_code={code}\n')
                self.assertFalse((root/'docker-calls').exists())
                calls = (root/'git-calls').read_text()
                self.assertIn('fetch', calls)
                if stage == 'fetch':
                    self.assertNotIn('checkout', calls)
                    self.assertFalse((root/'build-prepare.log').exists())
                    self.assertIn('fetch failure', (root/'build-upstream.log').read_text())
                else:
                    self.assertIn('checkout', calls)
                    self.assertIn('prepare failure', (root/'build-prepare.log').read_text())
                # A failed run is evidence: rerunning in-place must preserve it.
                before = (root/'build-exit.txt').read_bytes()
                again = subprocess.run(['bash', str(root/'scripts/build-dual-pf-ci.sh'), str(out)],
                                       env=env, capture_output=True, text=True)
                self.assertEqual(again.returncode, 2)
                self.assertEqual((root/'build-exit.txt').read_bytes(), before)

    def test_dangling_upstream_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.early_fixture(root, 'fetch')
            upstream = root/'build-upstream'
            upstream.symlink_to(root/'missing-target')
            result = subprocess.run(['bash', str(root/'scripts/build-dual-pf-ci.sh'), str(root/'build')],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(upstream.is_symlink())
            self.assertFalse((root/'missing-target').exists())
            self.assertFalse((root/'git-calls').exists())
            self.assertFalse((root/'docker-calls').exists())

    @staticmethod
    def early_fixture(root, stage):
        (root/'scripts').mkdir(); (root/'bin').mkdir()
        shutil.copy(ROOT/'scripts/build-dual-pf-ci.sh', root/'scripts')
        (root/'scripts/versions.sh').write_text('NCCL_COMMIT=pinned\nCUDA_IMAGE=unused\n')
        (root/'scripts/prepare_dual_pf.py').write_text(
            "import sys\nprint('prepare failure', file=sys.stderr)\nsys.exit(42)\n")
        stubs = {
            'uname': 'if [ "$1" = -s ]; then echo Linux; else echo aarch64; fi',
            'git': 'printf "%s\\n" "$*" >> "$GIT_CALLS"; '
                   'if [ "$1" = init ]; then mkdir "$3"; fi; '
                   'if [ "$3" = fetch ] && [ "$FAIL_STAGE" = fetch ]; then '
                   'echo "fetch failure" >&2; exit 41; fi; exit 0',
            'docker': 'echo unexpected >> "$DOCKER_CALLS"; exit 99',
            'file': 'exit 99', 'readelf': 'exit 99', 'strings': 'exit 99', 'sha256sum': 'exit 99',
        }
        for name, body in stubs.items():
            path = root/'bin'/name
            path.write_text('#!/bin/sh\n'+body+'\n'); path.chmod(0o755)
        return dict(os.environ, PATH=str(root/'bin')+os.pathsep+os.environ['PATH'],
                    GIT_CALLS=str(root/'git-calls'), DOCKER_CALLS=str(root/'docker-calls'),
                    FAIL_STAGE=stage)

    def test_local_builds_retain_unique_names_and_distribution_notices(self):
        """Exercise the real build wrapper up to Docker using CPU-only stubs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'scripts').mkdir(); (root/'bin').mkdir()
            shutil.copy(ROOT/'scripts/build-dual-pf-ci.sh', root/'scripts')
            (root/'scripts/versions.sh').write_text('NCCL_COMMIT=pinned\nCUDA_IMAGE=unused\n')
            (root/'scripts/prepare_dual_pf.py').write_text(
                "import pathlib,sys\n"
                "out=pathlib.Path(sys.argv[sys.argv.index('--output')+1])\n"
                "(out/'source').mkdir(parents=True)\n"
                "for name in ['LICENSE.txt','ThirdPartyNotices.txt']:\n"
                " (out/'source'/name).write_text(name+' original bytes')\n")
            for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
                shutil.copy(ROOT/name, root/name)
            stubs = {
                'uname': 'if [ "$1" = -s ]; then echo Linux; else echo aarch64; fi',
                'git': 'exit 0',
                'docker': 'printf "%s\\n" "$@" >> "$DOCKER_CALLS"; exit 44',
                'file': 'exit 99', 'readelf': 'exit 99',
                'sha256sum': 'exit 99', 'strings': 'exit 99',
            }
            for name, body in stubs.items():
                path = root/'bin'/name
                path.write_text('#!/bin/sh\n'+body+'\n'); path.chmod(0o755)
            env = dict(os.environ, PATH=str(root/'bin')+os.pathsep+os.environ['PATH'],
                       DOCKER_CALLS=str(root/'docker-calls'))
            env.pop('GITHUB_RUN_ID', None); env.pop('GITHUB_RUN_ATTEMPT', None)
            names = []
            for index in range(2):
                out = root/f'build-{index}'
                result = subprocess.run(['bash', str(root/'scripts/build-dual-pf-ci.sh'), str(out)],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 44, result.stderr)
                names.append((out/'container-name.txt').read_text().strip())
                self.assertRegex(names[-1], r'^dual-pf-local-[0-9a-f]{32}-1$')
                self.assertEqual((out/'exit.txt').read_text(), 'exit_code=44\n')
                for name in ('LICENSE.txt', 'ThirdPartyNotices.txt'):
                    self.assertEqual((out/'licenses'/name).read_bytes(), (out/'source'/name).read_bytes())
                for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
                    self.assertEqual((out/'licenses'/name).read_bytes(), (ROOT/name).read_bytes())
            self.assertNotEqual(*names)
            calls = (root/'docker-calls').read_text().splitlines()
            self.assertEqual(calls.count('run'), 2)
            self.assertNotIn('rm', calls); self.assertNotIn('--rm', calls)
            for name in names:
                self.assertIn(name, calls)
            workflow = (ROOT/'.github/workflows/nccl-arm64.yml').read_text()
            self.assertIn('${{ runner.temp }}/dual-pf/licenses/', workflow)

if __name__ == '__main__':
    unittest.main()
