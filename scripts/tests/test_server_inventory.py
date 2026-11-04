"""Workspace inventory selection and independent experiment snapshots."""
import importlib.util
from pathlib import Path
import tempfile
import tomllib
from types import SimpleNamespace
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'create_inference_project.py'
spec = importlib.util.spec_from_file_location('inventory_generator', SCRIPT)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

CATALOG = '''version = 1
[[servers]]
type = "Example GPU A"
alias = "gpu-a"
operations_command = "nvidia-smi"
[[servers.hosts]]
name = "a1"
address = "node-a1"
[[servers.hosts]]
name = "a2"
address = "node-a2"
[[servers]]
type = "Example GPU B"
alias = "gpu-b"
operations_command = "nvidia-smi"
[[servers.hosts]]
name = "b1"
address = "node-b1"
'''


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / 'workspace with spaces'
        self.workspace.mkdir()
        self.catalog = self.workspace / 'servers.toml'
        self.catalog.write_text(CATALOG, encoding='utf-8')

    def initialize(self, alias='gpu-a', model='model-a', hardware_type=None):
        args = SimpleNamespace(workspace=self.workspace, hardware=alias, model=model,
            framework='sglang', deployment='single', hardware_type=hardware_type)
        generator.initialize_config(args)
        return self.workspace / alias / model / 'sglang/single/environment.toml'

    def test_two_hardware_entries_and_multiple_hosts(self):
        for alias, hosts in [('gpu-a', ['node-a1', 'node-a2']), ('gpu-b', ['node-b1'])]:
            cfg = self.initialize(alias)
            data = tomllib.loads(cfg.read_text(encoding='utf-8'))
            self.assertEqual(data['server']['alias'], alias)
            self.assertEqual([h['address'] for h in data['server']['hosts']], hosts)
            self.assertEqual(data['server']['operations_command'], 'nvidia-smi')
            self.assertEqual(data['project']['workspace_dir'], '')

    def test_existing_snapshot_unchanged_when_catalog_changes(self):
        cfg = self.initialize()
        before = cfg.read_bytes()
        self.catalog.write_text(CATALOG.replace('node-a1', 'new-node'), encoding='utf-8')
        self.initialize()
        self.assertEqual(cfg.read_bytes(), before)
        new = self.initialize(model='model-b')
        self.assertIn('new-node', new.read_text(encoding='utf-8'))

    def test_no_fallback_for_unknown_alias_or_conflicting_type(self):
        with self.assertRaises(SystemExit): self.initialize('unknown')
        with self.assertRaises(SystemExit): self.initialize(hardware_type='Different GPU')
        self.assertFalse((self.workspace / 'unknown').exists())

    def test_invalid_catalog_is_rejected_before_directory_creation(self):
        for text in [CATALOG.replace('alias = "gpu-b"', 'alias = "gpu-a"'),
                     CATALOG.replace('name = "a2"', 'name = "a1"'),
                     CATALOG.replace('address = "node-a1"', 'address = ""'),
                     CATALOG.replace('address = "node-a1"', 'address = "node-a1"\ndevice_count = 4')]:
            with self.subTest(text=text):
                self.catalog.write_text(text, encoding='utf-8')
                with self.assertRaises(SystemExit): self.initialize()
                self.assertFalse((self.workspace / 'gpu-a').exists())

    def test_legacy_manual_init_without_inventory(self):
        self.catalog.unlink()
        cfg = self.initialize(hardware_type='Manual GPU')
        data = tomllib.loads(cfg.read_text(encoding='utf-8'))
        self.assertEqual(data['server']['type'], 'Manual GPU')
        self.assertEqual(data['server']['hosts'][0]['address'], '')


if __name__ == '__main__': unittest.main()
