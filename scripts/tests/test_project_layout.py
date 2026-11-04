"""Check experiment-local config placement without connecting to servers."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
GENERATOR = SCRIPTS / "create_inference_project.py"
spec = importlib.util.spec_from_file_location("project_generator", GENERATOR)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class ExperimentLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace with spaces"

    def run_generator(self, *args, ok=True):
        if "--init" not in args and "--remote" not in args and "--local-scaffold" not in args:
            args = (*args, "--local-scaffold")
        result = subprocess.run(
            [sys.executable, str(GENERATOR), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def init(self, model="model-a", deployment="single"):
        result = self.run_generator(
            "--init", "--workspace", self.workspace,
            "--hardware", "gpu", "--hardware-type", "Example GPU",
            "--model", model, "--framework", "sglang", "--deployment", deployment,
        )
        return Path(result.stdout.strip())

    def complete(self, config):
        text = config.read_text(encoding="utf-8")
        values = {
            "operations_command": "nvidia-smi", "name": "node-a", "address": "node-a",
            "workspace_dir": "/srv/inference", "host_models_dir": "/srv/models",
            "model_path": "/models/checkpoint",
        }
        for key, value in values.items():
            text = text.replace(f'{key} = ""', f'{key} = "{value}"')
        config.write_text(text, encoding="utf-8")

    def test_remote_generation_keeps_local_delivery_free_of_scripts(self):
        config = self.init()
        self.complete(config)
        remote_root = self.workspace / "remote source"
        text = config.read_text(encoding="utf-8").replace('workspace_dir = "/srv/inference"',
            'workspace_dir = ' + json.dumps(remote_root.as_posix()))
        config.write_text(text, encoding="utf-8")
        remote = remote_root / "gpu_model-a_sglang_single"
        remote.mkdir(parents=True)
        (remote / "coordination/bootstrap").mkdir(parents=True)
        remote_config = remote / "environment.toml"
        remote_config.write_text(text, encoding="utf-8")
        bootstrap = remote / "coordination/bootstrap/scripts"
        bootstrap.mkdir()
        shutil.copyfile(GENERATOR, bootstrap / GENERATOR.name)
        shutil.copytree(SCRIPTS / "templates", bootstrap / "templates", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        result = subprocess.run([sys.executable, str(bootstrap / GENERATOR.name), "--config", str(remote_config), "--remote"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((remote / "server/service.sh").is_file())
        self.assertTrue((remote / "experiment.env").is_file())
        self.assertFalse((config.parent / "server.sh").exists())
        self.assertEqual(list(config.parent.iterdir()), [config])
        validation = subprocess.run([sys.executable, str(SCRIPTS / "validate_inference_project.py"), str(remote), "--remote", "--scaffold"],
                                    capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_ordinary_generation_requires_explicit_remote_or_maintenance_mode(self):
        config = self.init()
        self.complete(config)
        result = subprocess.run([sys.executable, str(GENERATOR), "--config", str(config)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--remote", result.stderr)
        self.assertFalse((config.parent / "server.sh").exists())

    def test_remote_generation_rejects_wrong_config_destination(self):
        config = self.init()
        self.complete(config)
        result = self.run_generator("--config", config, "--remote", ok=False)
        self.assertIn("workspace_dir/title", result.stderr)

    def test_init_is_config_only_and_does_not_overwrite(self):
        config = self.init()
        self.assertEqual(config.parent, self.workspace / "gpu/model-a/sglang/single")
        self.assertEqual(list(config.parent.iterdir()), [config])
        self.assertFalse((self.workspace / "environment.toml").exists())
        original = config.read_bytes() + b"\n# user note\n"
        config.write_bytes(original)
        self.assertEqual(self.init(), config)
        self.assertEqual(config.read_bytes(), original)

    def test_multiple_models_and_methods_have_independent_configs(self):
        first = self.init()
        second = self.init("model-b", "pd")
        self.assertNotEqual(first, second)
        a = tomllib.loads(first.read_text(encoding="utf-8"))
        b = tomllib.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(a["project"]["model_name"], "model-a")
        self.assertEqual(b["project"]["deployment"], "pd")

    def test_generate_in_place_preserves_config_design_and_log(self):
        for method in ("single", "pd"):
            with self.subTest(method=method):
                config = self.init(deployment=method)
                self.complete(config)
                original = config.read_bytes()
                design = config.parent / "experiment.toml"
                design.write_text("# user design\nversion = 1\n", encoding="utf-8")
                log = config.parent / "LOG.md"
                log.write_text("Existing evidence\n", encoding="utf-8")
                self.run_generator("--config", config)
                self.assertTrue((config.parent / "server.sh").is_file())
                self.assertEqual((config.parent / "client/analyze_torch_trace.py").read_bytes(),
                                 (SCRIPTS / "templates/shared/client/analyze_torch_trace.py").read_bytes())
                title = "_".join(config.parent.parts[-4:])
                self.assertTrue((config.parent / f"{title}.md").is_file())
                self.assertFalse((config.parent / f"{title}_deployment.md").exists())
                self.assertFalse((config.parent / f"{title}_profiling.md").exists())
                self.assertTrue((config.parent / "run_source_variant.sh").is_file())
                self.assertFalse((config.parent / "tuning").exists())
                self.assertTrue((config.parent / "client/run_time_profile.py").is_file())
                self.assertFalse((config.parent / "AUTOTUNING_PLAN.md").exists())
                self.assertTrue((config.parent / "server/source_overrides/load.sh").is_file())
                self.assertTrue((config.parent / "server/source_overrides/manifest.env").is_file())
                self.assertTrue((config.parent / "server/source_overrides/baseline/framework").is_dir())
                self.assertTrue((config.parent / "server/source_overrides/baseline/operators").is_dir())
                self.assertFalse((config.parent / "gpu").exists())
                self.assertEqual(config.read_bytes(), original)
                self.assertEqual(design.read_text(encoding="utf-8"), "# user design\nversion = 1\n")
                self.assertEqual(log.read_text(encoding="utf-8"), "Existing evidence\n")
                checked = subprocess.run(
                    [sys.executable, str(SCRIPTS / "validate_inference_project.py"),
                     str(config.parent), "--scaffold"],
                    capture_output=True, text=True, encoding="utf-8",
                )
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.run_generator("--config", config, ok=False)

    def test_reject_incomplete_mismatched_or_shared_config(self):
        config = self.init()
        self.run_generator("--config", config, ok=False)
        self.complete(config)
        text = config.read_text(encoding="utf-8")
        config.write_text(text.replace('model_name = "model-a"', 'model_name = "other"'), encoding="utf-8")
        self.run_generator("--config", config, ok=False)
        config.write_text(text, encoding="utf-8")
        shared = self.workspace / "environment.toml"
        shared.write_text(text, encoding="utf-8")
        self.run_generator("--config", shared, ok=False)
        self.run_generator("--config", SCRIPTS.parent / "environment.toml", ok=False)
        self.assertFalse((config.parent / "server.sh").exists())


if __name__ == "__main__":
    unittest.main()
