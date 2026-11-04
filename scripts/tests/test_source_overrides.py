import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'


class SourceOverrideTests(unittest.TestCase):
    def setUp(self):
        self.bash = os.environ.get('NSYS_TEST_BASH') or shutil.which('bash')
        if not self.bash:
            self.skipTest('Bash is required; no installation is performed')
        self.temp = tempfile.TemporaryDirectory(prefix='overrides with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'server/source_overrides'
        self.base.mkdir(parents=True)
        for relative in ('framework/custom.py', 'operators/custom.py'):
            path = self.base / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text('# fixture\n', encoding='utf-8')
        self.loader = TEMPLATES / 'inference-project/server/source_overrides/load.sh'
        self.config = {
            'OVERRIDE_ROLES': ['server', 'prefill'],
            'OVERRIDE_FRAMEWORK_SOURCES': ['framework/custom.py'],
            'OVERRIDE_FRAMEWORK_TARGETS': ['/opt/example/framework.py'],
            'OVERRIDE_OPERATOR_SOURCES': ['operators/custom.py'],
            'OVERRIDE_OPERATOR_TARGETS': ['/opt/example/operator.py'],
            'OVERRIDE_FRAMEWORK_PYTHONPATH': [],
            'OVERRIDE_OPERATOR_PYTHONPATH': ['operators'],
            'OVERRIDE_BASE_PYTHONPATH': '/opt/example/original',
            'OVERRIDE_BASE_PYTHONPATH_CONFIRMED': '1',
        }

    def write_config(self):
        lines = []
        for key, value in self.config.items():
            if isinstance(value, list):
                rendered = '(' + ' '.join(shlex.quote(x) for x in value) + ')'
            else:
                rendered = shlex.quote(value)
            lines.append(key + '=' + rendered)
        (self.base / 'manifest.env').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def run_loader(self, mode, role='server'):
        self.write_config()
        script = 'set -eu; source "$1"; SOURCE_OVERRIDE_MODE=$3; source_override_load "$2" "$4"; printf "%s\\n" "${SOURCE_OVERRIDE_ARGS[@]}"'
        return subprocess.run([self.bash, '-c', script, 'test', self.loader.as_posix(),
                               self.root.as_posix(), mode, role], capture_output=True, text=True)

    def test_combined_mounts_both_and_preserves_pythonpath(self):
        r = self.run_loader('combined')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count('type=bind,'), 2)
        self.assertIn('dst=/opt/example/framework.py,readonly', r.stdout)
        self.assertIn('dst=/opt/example/operator.py,readonly', r.stdout)
        self.assertIn('PYTHONPATH=/server/source_overrides/operators:/opt/example/original', r.stdout)

    def test_modes_and_role_isolation(self):
        for mode, count in (('baseline', 0), ('framework', 1), ('operator', 1)):
            r = self.run_loader(mode)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.count('type=bind,'), count)
        r = self.run_loader('combined', 'decode')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('type=bind,', r.stdout)

    def test_duplicate_target_rejected(self):
        self.config['OVERRIDE_OPERATOR_TARGETS'] = self.config['OVERRIDE_FRAMEWORK_TARGETS']
        r = self.run_loader('combined')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Conflicting replacement target', r.stderr)

    def test_missing_file_and_mismatched_lists_rejected(self):
        self.config['OVERRIDE_OPERATOR_SOURCES'] = ['operators/missing.py']
        self.assertNotEqual(self.run_loader('operator').returncode, 0)
        self.config['OVERRIDE_OPERATOR_TARGETS'] = []
        self.assertNotEqual(self.run_loader('operator').returncode, 0)

    def test_path_escape_and_ambiguous_target_rejected(self):
        (self.root / 'outside.py').write_text('# outside\n', encoding='utf-8')
        self.config['OVERRIDE_OPERATOR_SOURCES'] = ['../../outside.py']
        self.assertNotEqual(self.run_loader('operator').returncode, 0)
        self.config['OVERRIDE_OPERATOR_SOURCES'] = ['operators/custom.py']
        self.config['OVERRIDE_OPERATOR_TARGETS'] = ['/opt/example/../operator.py']
        self.assertNotEqual(self.run_loader('operator').returncode, 0)

    def test_missing_role_or_pythonpath_confirmation_rejected(self):
        self.config['OVERRIDE_ROLES'] = []
        self.assertNotEqual(self.run_loader('operator').returncode, 0)
        self.config['OVERRIDE_ROLES'] = ['server']
        self.config['OVERRIDE_BASE_PYTHONPATH_CONFIRMED'] = '0'
        self.assertNotEqual(self.run_loader('operator').returncode, 0)

    def test_launchers_validate_before_lifecycle_and_insert_arguments(self):
        for template, role, args in (('inference-project', 'server', ['shell']),
                                     ('inference-project-pd', 'prefill', ['prefill'])):
            self.config['OVERRIDE_ROLES'] = [role]
            self.config['OVERRIDE_OPERATOR_TARGETS'] = ['/opt/example/operator.py']
            self.write_config()
            for relative in ('server.sh', 'server/source_overrides/load.sh'):
                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(TEMPLATES / template / relative, target)
            log = self.root / 'cli.log'
            env = ('record_cli() { if [[ "$1" == inspect ]]; then return 1; fi; '
                   'printf "%s\\n" "$@" >> ' + shlex.quote(log.as_posix()) + '; }\n'
                   'CONTAINER_CLI=(record_cli)\n'
                   'SERVER_CONTAINER_NAME=test\nPREFILL_CONTAINER_NAME=test\n'
                   'PREFILL_GPU_IDS=0\nSERVER_CONTAINER_ARGS=(run image)\n'
                   'HOST_MODELS_DIR=/example/models\nCONTAINER_MODELS_DIR=/models\nIMAGE=example\n')
            (self.root / 'experiment.env').write_text(env, encoding='utf-8')
            process_env = dict(os.environ, SOURCE_OVERRIDE_MODE='combined')
            r = subprocess.run([self.bash, (self.root / 'server.sh').as_posix(), *args],
                               env=process_env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(log.read_text().count('type=bind,'), 2)
            log.unlink()
            self.config['OVERRIDE_OPERATOR_TARGETS'] = self.config['OVERRIDE_FRAMEWORK_TARGETS']
            self.write_config()
            r = subprocess.run([self.bash, (self.root / 'server.sh').as_posix(), *args],
                               env=process_env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(log.exists(), 'Invalid config must fail before stopping or starting a container')

    def test_shared_protocol_is_identical_in_both_templates(self):
        for name in ('load.sh', 'manifest.env'):
            a = TEMPLATES / 'inference-project/server/source_overrides' / name
            b = TEMPLATES / 'inference-project-pd/server/source_overrides' / name
            self.assertEqual(a.read_bytes(), b.read_bytes())


if __name__ == '__main__':
    unittest.main()
