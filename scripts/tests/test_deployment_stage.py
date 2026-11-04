"""Deployment must not be blocked by unfinished future-stage scaffolding."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'validate_inference_project.py'
spec = importlib.util.spec_from_file_location('deployment_validator', SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

class DeploymentStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'gpu/model/vllm/single'
        self.project.mkdir(parents=True)
        (self.project/'environment.toml').write_text('[server]\nalias="gpu"\n[project]\nmodel_name="model"\nframework="vllm"\ndeployment="single"\n')
        (self.project/'experiment.env').write_text('PREFIX_CACHE_MODE=disabled\nPREFIX_CACHE_DEFAULT_DISABLED=1\nSSH_TARGETS=(node)\nSERVICE_CMD=(vllm serve)\nSERVICE_ARGS=(/models/model)\nSERVER_CONTAINER_ARGS=(run server)\nCLIENT_CONTAINER_ARGS=(run client)\nPROFILE_SECONDS=<AI:future>\n')
        for name in ('server.sh','server/service.sh','client.sh','client/chat_test.sh'):
            path=self.project/name
            path.parent.mkdir(exist_ok=True)
            path.write_text('#!/bin/bash\n')

    def test_allows_unprepared_workload_profiling_and_report(self):
        (self.project/'experiment.toml').write_text('version=1\n[parallelism]\ntensor_parallel_size=1\n')
        (self.project/'future.md').write_text('TODO: future analysis')
        self.assertEqual(validator.validate_deployment(self.project), [])

    def test_rejects_actual_startup_placeholder_and_wrong_target(self):
        env=self.project/'experiment.env'
        env.write_text(env.read_text().replace('/models/model','<AI:model>'))
        self.assertIn('unresolved deployment command/path placeholder', validator.validate_deployment(self.project))
        config=self.project/'environment.toml'
        config.write_text(config.read_text().replace('alias="gpu"','alias="other"'))
        self.assertIn('experiment directory identity differs from environment.toml', validator.validate_deployment(self.project))

    def test_rejects_unfilled_container_command_and_missing_prefix_disable(self):
        env = self.project / 'experiment.env'
        env.write_text(env.read_text().replace('SERVER_CONTAINER_ARGS=(run server)', 'SERVER_CONTAINER_ARGS=()')
                       .replace('PREFIX_CACHE_DEFAULT_DISABLED=1', 'PREFIX_CACHE_DEFAULT_DISABLED=0'))
        errors = validator.validate_deployment(self.project)
        self.assertIn('experiment.env missing server container arguments', errors)
        self.assertIn('no-prefix startup lacks disable arguments or disabled framework default', errors)

    def test_rejects_design_runtime_prefix_conflict(self):
        (self.project / 'experiment.toml').write_text('[cache]\nprefix_cache_enabled=true\n')
        self.assertIn('deployment design conflicts with disabled prefix cache', validator.validate_deployment(self.project))

    def test_bootstrap_and_archived_study_are_not_active_placeholder_inputs(self):
        for name in ('coordination/bootstrap/scripts/templates/service.sh', 'tuning/old/configuration/experiment.env'):
            path = self.project / name
            path.parent.mkdir(parents=True)
            path.write_text('SERVICE_CMD=(TODO)')
            self.assertFalse(validator.is_active_source(path, self.project))
        self.assertTrue(validator.is_active_source(self.project / 'server/service.sh', self.project))

    def test_remote_layout_uses_configured_workspace_and_title(self):
        remote_root = Path(self.temp.name) / 'remote'
        remote = remote_root / 'gpu_model_vllm_single'
        remote.mkdir(parents=True)
        self.assertTrue(validator.environment_location_matches(remote.resolve(), {'alias': 'gpu'},
            {'model_name': 'model', 'framework': 'vllm', 'deployment': 'single',
             'workspace_dir': str(remote_root)}, remote_layout=True))
        self.assertFalse(validator.environment_location_matches(remote.resolve(), {'alias': 'other'},
            {'model_name': 'model', 'framework': 'vllm', 'deployment': 'single',
             'workspace_dir': str(remote_root)}, remote_layout=True))

if __name__ == '__main__':
    unittest.main()
