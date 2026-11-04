"""Load the profiling-only hook lazily without modifying the installed framework."""

import importlib
import importlib.abc
import importlib.machinery
import os
import sys


TARGET = os.environ.get("PROFILE_MANAGER_MODULE", "")
HOOK_MODULE = os.environ.get("PROFILE_HOOK_MODULE", "")


class HookLoader(importlib.abc.Loader):
    def __init__(self, original):
        self.original = original

    def create_module(self, spec):
        return self.original.create_module(spec)

    def exec_module(self, module):
        self.original.exec_module(module)
        hook = importlib.import_module(HOOK_MODULE)
        hook.install(module)


class HookFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not TARGET or fullname != TARGET:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot locate profiler manager: {TARGET}")
        spec.loader = HookLoader(spec.loader)
        return spec


if os.environ.get("PROFILE_HOOK_ENABLED") == "1":
    if not TARGET or not HOOK_MODULE:
        raise RuntimeError("PROFILE_MANAGER_MODULE and PROFILE_HOOK_MODULE are required")
    sys.meta_path.insert(0, HookFinder())
