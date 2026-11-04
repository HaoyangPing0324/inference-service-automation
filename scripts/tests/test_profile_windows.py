"""Behavioral tests: no GPU, remote host, or SGLang installation required."""
import asyncio
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "scripts/templates/inference-project/client/profile_windows.py"
spec = importlib.util.spec_from_file_location("windows", CLIENT)
windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(windows)


class TestWindows(unittest.TestCase):
    def test_router_readiness_checks_both_exact_roles(self):
        healthy={'workers':[{'url':'http://p','worker_type':'prefill','is_healthy':True},
                            {'url':'http://d','worker_type':'decode','is_healthy':True}]}
        self.assertTrue(windows.pd_workers_ready(healthy,['http://p'],['http://d']))
        healthy['workers'][0]['is_healthy']=False
        self.assertFalse(windows.pd_workers_ready(healthy,['http://p'],['http://d']))
        healthy['workers'][0]['is_healthy']=True
        self.assertFalse(windows.pd_workers_ready(healthy,['http://wrong'],['http://d']))

    def exercise(self, c, pd):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(concurrency=c, output_dir=Path(tmp), base_url="http://router",
                prefill_url=["http://p"] if pd else [], decode_url=["http://d"] if pd else [],
                prefix="test", mode="torch", prefill_steps=4, decode_steps=128 if pd else 4,
                isl=16384, osl=2048, dataset_path="local.json", model_path="model",
                seed=1, request_timeout=10, control_timeout=10)
            lock = threading.Lock()
            active = maximum = generated = 0
            calls = []
            def transport(url, body, timeout):
                nonlocal active, maximum, generated
                with lock:
                    calls.append((url, body))
                if url.endswith("/generate"):
                    with lock:
                        active += 1
                        maximum = max(maximum, active)
                        generated += 1
                    time.sleep(0.002)
                    with lock:
                        active -= 1
                    return json.dumps({"meta_info": {"completion_tokens": 2048}})
                return "OK"
            run = windows.WindowRun(args, [SimpleNamespace(prompt="hi")] * (5*c), transport)
            healthy={'workers':[{'url':url,'worker_type':role,'is_healthy':True}
                     for role,urls in [('prefill',args.prefill_url),('decode',args.decode_url)] for url in urls]}
            with patch.object(windows,'get_workers',lambda url:healthy):
                asyncio.run(run.run())
            self.assertEqual((run.completed, run.successful, generated), (5*c, 5*c, 5*c+2))
            self.assertLessEqual(maximum, c)
            starts = [body for url, body in calls if url.endswith("/start_profile")]
            self.assertEqual(len(starts), 4 if pd else 2)
            self.assertEqual([body["num_steps"] for body in starts], [4,128,4,128] if pd else [4,4])
            events = [e for e in run.events if e["event"] == "after-prerun-started"]
            self.assertEqual(len(events), 1)
            self.assertGreaterEqual(events[0]["completed"], 4*c)
            initial = [e for e in run.events if e["event"] == "profile-control"
                       and e["phase"] == "initial" and e["endpoint"].endswith("start_profile")]
            self.assertTrue(all(e["completed"] == 0 for e in initial))
            result = json.loads((Path(tmp)/"workload.json").read_text())
            self.assertEqual(result["after_prerun_target_completed"], 4*c)

    def test_single_native_equal_steps_c1(self): self.exercise(1, False)
    def test_single_native_equal_steps_c16(self): self.exercise(16, False)
    def test_pd_c1(self): self.exercise(1, True)
    def test_pd_c16(self): self.exercise(16, True)

    def test_single_unequal_steps_rejected_before_requests(self):
        args=SimpleNamespace(concurrency=1,prefill_url=[],decode_url=[],base_url="http://single",
                             prefill_steps=4,decode_steps=128)
        with self.assertRaisesRegex(ValueError,"Single-service native"):
            windows.WindowRun(args,[])


class TestNativeAdapter(unittest.TestCase):
    def exercise(self, role, short=False):
        import os
        from unittest.mock import patch
        path = ROOT / "scripts/templates/inference-project-pd/server/profiling_hooks/__HOOK_MODULE__.py"
        with patch.dict(os.environ, {"PROFILE_PREFIX":"test", "PROFILE_ROLE":role,
                "PROFILE_PREFILL_STEPS":"4", "PROFILE_DECODE_STEPS":"128",
                "PROFILE_KEY_AVERAGES_ENABLED":"0"}):
            spec = importlib.util.spec_from_file_location("hook", path)
            hook = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hook)
        class Mode:
            def __init__(self, name): self.name=name
            def is_prefill(self): return self.name == "p"
            def is_decode(self): return self.name == "d"
        class Manager:
            profile_in_progress=False
            torch_profiler=None
            def _init_profile(self, output_dir, start_step, num_steps, activities, with_stack,
                    record_shapes, profile_by_stage, profile_id, merge_profiles=False,
                    profile_prefix="", detailed_annotations=False, profile_stages=None):
                self.torch_profiler_output_dir=output_dir
                self.profile_id=profile_id
                self.profiler_prefill_ct=self.profiler_decode_ct=0
                self.profiler_target_prefill_ct=self.profiler_target_decode_ct=num_steps
                return SimpleNamespace(success=True)
            def _stop_profile(self, stage=None):
                self.profile_in_progress=False
                return SimpleNamespace(success=True)
            def _profile_batch_predicate(self, batch):
                name="prefill" if batch.forward_mode.is_prefill() else "decode"
                key="profiler_"+name+"_ct"
                count=getattr(self,key)
                if count == 0: self.profile_in_progress=True
                setattr(self,key,count+1)
                if count+1 > getattr(self,"profiler_target_"+name+"_ct") and self.profile_in_progress:
                    self._stop_profile()
        module=SimpleNamespace(SchedulerProfilerManager=Manager,
            envs=SimpleNamespace(SGLANG_PROFILE_V2=SimpleNamespace(get=lambda:False)),
            ProfileReqOutput=lambda **kw:SimpleNamespace(**kw),
            get_parallel=lambda:SimpleNamespace(tp_rank=0),
            ForwardMode=SimpleNamespace(EXTEND="p",DECODE="d"))
        hook.install(module)
        with tempfile.TemporaryDirectory() as tmp:
            m=Manager()
            for phase in ("initial","after-prerun"):
                out=Path(tmp)/phase
                m._init_profile(str(out),None,4,["CPU"],False,False,True,phase,
                                profile_prefix="test-"+phase)
                stages=("p","d") if role == "single" else ("p" if role=="prefill" else "d",)
                for name in stages:
                    count=2 if short and name=="p" else 4 if name=="p" else 128
                    for _ in range(count+ (0 if short else 1)):
                        m._profile_batch_predicate(SimpleNamespace(forward_mode=Mode(name),batch_size=lambda:1))
                m._stop_profile()
                for name in stages:
                    stage="prefill" if name=="p" else "decode"
                    data=json.loads((out/f"window-{stage}-TP-0.json").read_text())
                    target=4 if name=="p" else 128
                    self.assertEqual(data["captured_steps"],2 if short else target)
                    self.assertEqual(data["complete"],not short)
                    self.assertEqual(data["phase"],phase)
    def test_prefill(self): self.exercise("prefill")
    def test_decode(self): self.exercise("decode")
    def test_single(self): self.exercise("single")
    def test_two_chunks_is_incomplete(self): self.exercise("prefill",True)


if __name__ == "__main__": unittest.main()
