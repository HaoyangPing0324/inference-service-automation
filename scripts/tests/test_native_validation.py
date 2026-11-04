import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("native",ROOT/"scripts/templates/inference-project-pd/client/validate_native_windows.py")
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class TestNativeValidation(unittest.TestCase):
    def test_actual_steps_and_primary_track_not_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"trace.json.gz"
            events=[{"cat":"gpu_user_annotation","ph":"X","pid":1,"tid":1,
                     "name":f"step[EXTEND bs={i+1} toks=4096]"} for i in range(4)]
            # A second CUDA track must not double the scheduler step count.
            events += [dict(e,tid=2) for e in events]
            with gzip.open(path,"wt") as f: json.dump({"traceEvents":events},f)
            result=native.summarize(path,"initial","prefill",0,4)
            self.assertTrue(result["complete"])
            self.assertEqual(result["captured_steps"],4)
            self.assertEqual((result["batch_size_min"],result["batch_size_max"]),(1,4))
            self.assertFalse(native.summarize(path,"initial","prefill",0,8)["complete"])

    def test_truncated_trace_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"trace.json.gz"
            with gzip.open(path,"wt") as f: f.write('{"traceEvents":[{"name":')
            with self.assertRaises(ValueError): list(native.events(path))

    def test_speculative_decode_counts_verify_not_draft_plus_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.json.gz'
            rows=[{'cat':'user_annotation','ph':'X','pid':1,'tid':1,
                   'name':f'step[{stage} bs=4]'}
                  for _ in range(128) for stage in ('DRAFT','VERIFY')]
            with gzip.open(path,'wt') as f:json.dump({'traceEvents':rows},f)
            result=native.summarize(path,'initial','decode',0,128)
            self.assertTrue(result['complete'])
            self.assertEqual(result['captured_steps'],128)


if __name__ == "__main__": unittest.main()
