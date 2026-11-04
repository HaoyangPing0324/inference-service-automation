"""CPU tests using installed SGLang init/predicate and the actual shell chain."""
import argparse
import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch


class Mode:
    def __init__(self, name): self.name = name
    def is_prefill(self): return self.name == 'EXTEND'
    def is_decode(self): return self.name == 'DECODE'


class Tests(unittest.TestCase):
    def build(self, role='single'):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        clsnode = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SchedulerProfilerManager')
        methods = [n for n in clsnode.body if isinstance(n, ast.FunctionDef) and n.name in ('_init_profile', '_profile_batch_predicate')]
        env = {'envs': NS(SGLANG_PROFILE_V2=NS(get=lambda: False)),
               'ProfileReqOutput': lambda **kw: NS(**kw), 'Path': Path, 'os': os}
        code = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
            ast.ClassDef(name='Manager', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
        exec(compile(ast.fix_missing_locations(code), str(SOURCE), 'exec'), env)
        cls = env['Manager']
        def start(obj, stage):
            self.assertFalse(obj.profile_in_progress, 'Must not overwrite a live profiler')
            obj.profile_in_progress = True
            obj.seen = []
            return NS(success=True)
        def stop(obj, stage=None):
            if obj.profile_in_progress: obj.saved.append((stage.name if stage else None, obj.seen[:]))
            obj.profile_in_progress = False
            return NS(success=True)
        cls._start_profile, cls._stop_profile = start, stop
        original = cls._profile_batch_predicate
        spec = importlib.util.spec_from_file_location('single_capture', HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        with patch.dict(os.environ, PROFILE_ROLE=role, PROFILE_PREFIX='test', PROFILE_PREFILL_STEPS='4', PROFILE_DECODE_STEPS='128'):
            hook.install(NS(SchedulerProfilerManager=cls, ForwardMode=NS(EXTEND=Mode('EXTEND'), DECODE=Mode('DECODE')), **env))
        obj = cls()
        obj.profile_in_progress = False
        obj.get_forward_ct = lambda: 0
        obj.saved = []
        return obj, original

    def arm(self, obj, phase):
        with patch.dict(os.environ, PROFILE_PREFILL_STEPS='4', PROFILE_DECODE_STEPS='128'):
            result = obj._init_profile('.', None, 4, ['CPU'], False, False, True, phase, profile_prefix='test-' + phase)
        self.assertTrue(result.success)

    def forward(self, obj, name):
        obj._profile_batch_predicate(NS(forward_mode=Mode(name), batch_size=lambda: 16))
        if obj.profile_in_progress: obj.seen.append(name)

    def test_rearm_decode_first_both_windows(self):
        obj, _ = self.build()
        for phase in ('initial', 'after-prerun'):
            self.arm(obj, phase)
            for mode in ['DECODE'] * 7 + ['EXTEND'] * 4 + ['DECODE'] * 128 + ['EXTEND', 'DECODE']:
                self.forward(obj, mode)
            self.assertEqual(obj.saved[-2:], [('EXTEND', ['EXTEND'] * 4), ('DECODE', ['DECODE'] * 128)])

    def test_interleaved_prefill_does_not_overwrite_decode(self):
        obj, _ = self.build()
        self.arm(obj, 'initial')
        for mode in ['EXTEND'] * 4 + ['DECODE'] * 50 + ['EXTEND'] + ['DECODE'] * 79:
            self.forward(obj, mode)
        self.assertEqual(obj.saved[-1][0], 'DECODE')
        self.assertEqual(obj.saved[-1][1].count('DECODE'), 128)

    def test_short_window_retains_stage(self):
        obj, _ = self.build()
        self.arm(obj, 'after-prerun')
        self.forward(obj, 'EXTEND')
        obj._stop_profile()
        self.assertEqual(obj.saved, [('EXTEND', ['EXTEND'])])

    def test_pd_roles_unchanged(self):
        for role in ('prefill', 'decode'):
            obj, original = self.build(role)
            self.assertIs(type(obj)._profile_batch_predicate, original)
            self.arm(obj, 'initial')
            self.assertEqual(obj.profiler_target_decode_ct, 4)

    def test_actual_shell_entry_preserves_approval(self):
        if not CONTAINER and not Path('/server/profile_service.sh').is_file():
            self.skipTest('Pass --container to test the actual Linux container entry chain')
        with tempfile.TemporaryDirectory(dir=SOURCE.parent if CONTAINER else None) as tmp:
            cfg = Path(tmp) / 'test.env'
            cfg.write_text('PROFILE_PROTOCOL=steps\nPROFILE_HOOK_ENABLED=0\nPROFILE_MANAGER_MODULE=x\nPROFILE_HOOK_MODULE=y\n'
                'PROFILE_PREFIX=test\nPROFILE_PREFILL_SCOPE=steps\nPROFILE_PREFILL_STEPS=4\nPROFILE_DECODE_STEPS=128\n'
                'PROFILE_SINGLE_STAGE_ADAPTER_APPROVED=1\nPROFILE_FRAMEWORK_ENV=()\n'
                'SERVICE_CMD=(env)\nSERVICE_ARGS=(-0)\nPREFIX_CACHE_MODE=disabled\n'
                'PREFIX_CACHE_DISABLE_ARGS=()\nPREFIX_CACHE_DEFAULT_DISABLED=1\n', encoding='utf-8')
            cmd = ['bash', '/server/profile_service.sh', 'no-key-averages']
            if CONTAINER:
                mapped = '/server/' + cfg.relative_to(SOURCE.parent).as_posix()
                cmd = ['docker', 'exec', '-e', 'EXPERIMENT_ENV=' + mapped, CONTAINER] + cmd
            result = subprocess.run(cmd,
                env={**os.environ, 'EXPERIMENT_ENV': str(cfg)}, check=True, capture_output=True)
            self.assertIn(b'PROFILE_HOOK_ENABLED=1\0', result.stdout)
            self.assertIn(b'PROFILE_ROLE=single\0', result.stdout)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--hook', type=Path, required=True)
    p.add_argument('--container')
    args = p.parse_args()
    SOURCE, HOOK = args.source.resolve(), args.hook.resolve()
    CONTAINER = args.container
    unittest.main(argv=['test_single_capture'], verbosity=2)
