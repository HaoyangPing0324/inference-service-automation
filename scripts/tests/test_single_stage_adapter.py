import importlib.util
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class TestSingleStageAdapter(unittest.TestCase):
    def test_single_targets_and_unrelated_prefix(self):
        path=Path(__file__).resolve().parents[1]/'templates/inference-project/server/profiling_hooks/__HOOK_MODULE__.py'
        spec=importlib.util.spec_from_file_location('single_adapter',path)
        hook=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        class Manager:
            def _init_profile(self, profile_prefix, num_steps):
                self.profiler_target_prefill_ct=self.profiler_target_decode_ct=num_steps
                return SimpleNamespace(success=True)
            def _profile_batch_predicate(self,batch):pass
            def _stop_profile(self):pass
        predicate,stop=Manager._profile_batch_predicate,Manager._stop_profile
        module=SimpleNamespace(SchedulerProfilerManager=Manager,
            envs=SimpleNamespace(SGLANG_PROFILE_V2=SimpleNamespace(get=lambda:False)))
        with patch.dict(os.environ,{'PROFILE_ROLE':'single','PROFILE_PREFIX':'test','PROFILE_PREFILL_STEPS':'4','PROFILE_DECODE_STEPS':'128'}):
            hook.install(module)
            obj=Manager()
            for phase in ('initial','after-prerun'):
                obj._init_profile('test-'+phase,4)
                self.assertEqual((obj.profiler_target_prefill_ct,obj.profiler_target_decode_ct),(4,128))
            obj._init_profile('unrelated',7)
            self.assertEqual((obj.profiler_target_prefill_ct,obj.profiler_target_decode_ct),(7,7))
            self.assertIsNone(obj._single_capture_state)
        self.assertIsNot(Manager._profile_batch_predicate,predicate)
        self.assertIsNot(Manager._stop_profile,stop)

    def test_pd_roles_do_not_install_single_capture(self):
        path=Path(__file__).resolve().parents[1]/'templates/inference-project/server/profiling_hooks/__HOOK_MODULE__.py'
        spec=importlib.util.spec_from_file_location('single_adapter_guard',path)
        hook=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        for role in ('prefill','decode',''):
            class Manager: pass
            with patch.dict(os.environ,{'PROFILE_ROLE':role}):
                hook.install(SimpleNamespace(SchedulerProfilerManager=Manager))
            self.assertFalse(hasattr(Manager,'_single_stage_targets_installed'))

if __name__=='__main__':unittest.main()
