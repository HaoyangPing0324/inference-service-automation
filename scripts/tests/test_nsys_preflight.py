import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest


class TestNsysPreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = os.environ.get('NSYS_TEST_BASH') or shutil.which('bash')
        if not cls.bash:
            raise unittest.SkipTest('Bash required: run on the confirmed Linux host or supply NSYS_TEST_BASH')
        cls.script = Path(__file__).resolve().parents[1] / 'templates/inference-project/server/nsys_preflight.sh'

    def run_check(self, files):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, value in files.items():
                (root / name).write_text(value, encoding='utf-8')
            return subprocess.run([self.bash, self.script.as_posix(), root.as_posix()],
                                  capture_output=True, text=True)

    def test_readable_topology(self):
        result = self.run_check(dict.fromkeys(('online', 'possible', 'present'), '0-15\n'))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_topology_fails(self):
        result = self.run_check({'online': '0-15\n'})
        self.assertEqual(result.returncode, 2)
        self.assertIn('possible', result.stderr)

    def test_empty_topology_fails(self):
        result = self.run_check({'online': ''})
        self.assertEqual(result.returncode, 2)
        self.assertIn('online', result.stderr)

    def test_container_mount_only_in_explicit_nsys_mode(self):
        source = self.script.parents[1] / 'server.sh'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = root / 'server.sh'
            entry.write_bytes(source.read_bytes())
            log = root / 'calls.txt'
            (root / 'experiment.env').write_text(
                'record_cli() { printf "%s\\n" "$@" >> '
                + shlex.quote(log.as_posix()) + '; }\n'
                'CONTAINER_CLI=(record_cli)\n'
                'SERVER_CONTAINER_ARGS=(run --name example image)\n'
                'SERVER_CONTAINER_NAME=example\n', encoding='utf-8')
            for mode in ('shell', 'nsys'):
                log.write_text('', encoding='utf-8')
                result = subprocess.run([self.bash, entry.as_posix(), mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = log.read_text(encoding='utf-8').splitlines()
                self.assertEqual('type=bind,src=/sys,dst=/sys,readonly' in args,
                                 mode == 'nsys')
                self.assertEqual(args[-4:], ['exec', '-it', 'example', 'bash'])

    def test_pd_nsys_mounts_topology_but_normal_roles_do_not(self):
        source = self.script.parents[2] / 'inference-project-pd/server.sh'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = root / 'server.sh'
            entry.write_bytes(source.read_bytes())
            log = root / 'calls.txt'
            (root / 'experiment.env').write_text(
                'record_cli() { [[ "$1" != inspect ]] || return 1; printf "%s\\n" "$@" >> '
                + shlex.quote(log.as_posix()) + '; }\n'
                'CONTAINER_CLI=(record_cli)\nSERVER_CONTAINER_ARGS=(--network host)\n'
                'PREFILL_CONTAINER_NAME=p\nDECODE_CONTAINER_NAME=d\nPREFILL_GPU_IDS=0\nDECODE_GPU_IDS=1\n'
                'HOST_MODELS_DIR=/models\nCONTAINER_MODELS_DIR=/models\nIMAGE=example\n', encoding='utf-8')
            for mode in ('prefill', 'decode', 'nsys-prefill', 'nsys-decode'):
                log.write_text('', encoding='utf-8')
                result = subprocess.run([self.bash, entry.as_posix(), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = log.read_text(encoding='utf-8').splitlines()
                self.assertEqual('type=bind,src=/sys,dst=/sys,readonly' in args, mode.startswith('nsys-'))


if __name__ == '__main__':
    unittest.main()
