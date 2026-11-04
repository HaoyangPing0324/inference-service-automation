import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("collector",Path(__file__).resolve().parents[1]/"collect_profiler_results.py")
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class TestCollector(unittest.TestCase):
    def test_invalid_run_and_dimensions_rejected_before_remote_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            for run, concurrency, tp in (('../escape', 1, 1), ('bad\\run', 1, 1), ('--option', 1, 1), ('run', 0, 1), ('run', 1, -1)):
                args = SimpleNamespace(project=Path(tmp), concurrency=concurrency, tp_size=tp,
                    run=run, remote_project='/runtime/project', result_owner=None)
                with self.subTest(run=run, concurrency=concurrency, tp=tp), patch.object(collector, 'remote_text') as remote:
                    with self.assertRaises(ValueError):
                        collector.collect(args)
                    remote.assert_not_called()
    def test_single_source_is_split_into_prefill_and_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            owner = project/'tuning/study-a/candidates/variant-a'
            owner.mkdir(parents=True)
            sibling = project/'tuning/study-a/candidates/variant-b/profiling_results/profiler/C1'
            sibling.mkdir(parents=True)
            (sibling/'keep').write_text('other candidate')
            root_result = project/'profiling_results/profiler/C1'
            root_result.mkdir(parents=True)
            (root_result/'keep').write_text('original experiment')
            args=SimpleNamespace(project=Path(tmp),concurrency=1,replace=False,
                result_owner='tuning/study-a/candidates/variant-a',
                remote_project='/runtime/project',run='single-run',prefill_host='same',decode_host='same',tp_size=1)
            payload=b'example'
            digest=hashlib.sha256(payload).hexdigest()
            sources=[]
            def remote(host,path):
                if path.name=='job.exitcode':return '0'
                if path.name=='workload.json':return json.dumps({'C':1,'K':5,'completed':5,'successful':5})
                role='prefill' if 'prefill' in path.name else 'decode'
                return json.dumps([{'phase':phase,'tp_rank':0,'role':role,'complete':True,
                    'captured_steps':4 if role=='prefill' else 128,'trace':role+'.trace.json.gz',
                    'bytes':len(payload),'sha256':digest,'source_subdir':phase}
                    for phase in ('initial','after-prerun')])
            def fetch(host,source,destination):
                sources.append(source)
                destination.write_bytes(payload)
            with patch.object(collector,'remote_text',remote),patch.object(collector,'fetch',fetch):
                output=collector.collect(args)
            self.assertEqual(output, owner/'profiling_results/profiler/C1')
            self.assertEqual((sibling/'keep').read_text(),'other candidate')
            self.assertEqual((root_result/'keep').read_text(),'original experiment')
            self.assertIn('tuning/study-a/candidates/variant-a',(output/'MANIFEST.md').read_text())
            for phase in ('initial','after-prerun'):
                for role in ('prefill','decode'):
                    self.assertTrue((output/phase/role/'TP-0.trace.json.gz').is_file())
            self.assertTrue(all(source.parent.name in ('initial','after-prerun') for source in sources))

    def test_result_owner_accepts_existing_baseline_and_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp).resolve()
            owner=project/'tuning/study-a/baseline'
            owner.mkdir(parents=True)
            self.assertEqual(collector.resolve_result_owner(project),project)
            self.assertEqual(collector.resolve_result_owner(project,'tuning/study-a/baseline'),owner)

    def test_result_owner_rejects_unsafe_or_missing_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)
            for scope in ('../outside','/tmp/results','tuning/a/candidates/../baseline',
                          'tuning/a','other/a/baseline','tuning/a/candidates/x/extra',
                          'tuning/a/candidates/x','tuning\\a\\baseline'):
                with self.subTest(scope=scope),self.assertRaises((ValueError,FileNotFoundError)):
                    collector.resolve_result_owner(project,scope)

    def test_checked_layout_and_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(project=Path(tmp),concurrency=16,replace=False,
                remote_project="/runtime/project",run="run-id",prefill_host="p",decode_host="d",tp_size=1)
            payload=b"verified gzip placeholder; native side already validated"
            digest=hashlib.sha256(payload).hexdigest()
            def remote(host,path):
                if path.name == "job.exitcode":return "0"
                if path.name == "workload.json":return json.dumps({"C":16,"K":5,"completed":80,"successful":80})
                role="prefill" if host=="p" else "decode"
                count=4 if host=="p" else 128
                return json.dumps([{"phase":phase,"tp_rank":0,"role":role,"complete":True,
                    "captured_steps":count,"trace":"source.trace.json.gz","bytes":len(payload),
                    "sha256":digest} for phase in ("initial","after-prerun")])
            def fetch(host,source,destination):destination.write_bytes(payload)
            with patch.object(collector,"remote_text",remote),patch.object(collector,"fetch",fetch):
                output=collector.collect(args)
            self.assertEqual(len(list(output.rglob("*.trace.json.gz"))),4)
            self.assertTrue((output/"after-prerun/decode/TP-0.trace.json.gz").is_file())
            before=(output/"MANIFEST.md").read_bytes()
            args.replace=True
            def bad_fetch(host,source,destination):destination.write_bytes(b"bad")
            with patch.object(collector,"remote_text",remote),patch.object(collector,"fetch",bad_fetch):
                with self.assertRaisesRegex(ValueError,"Size/hash mismatch"):
                    collector.collect(args)
            self.assertEqual((output/"MANIFEST.md").read_bytes(),before)


if __name__ == "__main__":unittest.main()
