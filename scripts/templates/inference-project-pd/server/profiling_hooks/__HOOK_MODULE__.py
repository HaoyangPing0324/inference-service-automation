"""Bounded two-phase SGLang v0.5.x adapter using its native stage counters.

Not a generic framework hook. Revalidate manager signatures after upgrades.
"""
import inspect
import json
import os
from pathlib import Path

PREFIX = os.environ.get("PROFILE_PREFIX", "")
ROLE = os.environ.get("PROFILE_ROLE", "single")
PREFILL_STEPS = int(os.environ.get("PROFILE_PREFILL_STEPS", "4"))
DECODE_STEPS = int(os.environ.get("PROFILE_DECODE_STEPS", "128"))
KEY_AVERAGES_ENABLED = os.environ.get("PROFILE_KEY_AVERAGES_ENABLED", "0") == "1"


def install(module):
    cls = module.SchedulerProfilerManager
    if getattr(cls, "_bounded_windows_installed", False):
        return
    old_init, old_predicate, old_stop = cls._init_profile, cls._profile_batch_predicate, cls._stop_profile
    signature = inspect.signature(old_init)

    def init(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        prefix = bound.arguments.get("profile_prefix", "")
        if not PREFIX or prefix not in (PREFIX + "-initial", PREFIX + "-after-prerun"):
            self._bounded_window = None
            return old_init(self, *args, **kwargs)
        if module.envs.SGLANG_PROFILE_V2.get():
            return module.ProfileReqOutput(success=False, message="Bounded adapter requires PROFILE_V2=0")
        # Keep native step-based capture; only supply different stage targets.
        bound.arguments.update(profile_by_stage=True, start_step=None, num_steps=PREFILL_STEPS)
        result = old_init(*bound.args, **bound.kwargs)
        if result.success:
            self.profiler_target_prefill_ct = PREFILL_STEPS
            self.profiler_target_decode_ct = DECODE_STEPS
            self._bounded_window = {
                "phase": prefix[len(PREFIX) + 1:],
                "prefill": {"count": 0, "min": None, "max": None},
                "decode": {"count": 0, "min": None, "max": None},
                "active": None,
            }
        return result

    def save(self, stage, averages=None, error=None):
        state = self._bounded_window
        entry = state[stage]
        rank = module.get_parallel().tp_rank
        target = PREFILL_STEPS if stage == "prefill" else DECODE_STEPS
        output = Path(self.torch_profiler_output_dir)
        output.mkdir(parents=True, exist_ok=True)
        summary = {
            "phase": state["phase"], "role": ROLE, "stage": stage, "tp_rank": rank,
            "profile_id": self.profile_id, "captured_steps": entry["count"],
            "target_steps": target, "complete": entry["count"] == target,
            "prefill_scope": "steps", "prefill_batches": state["prefill"]["count"],
            "decode_steps": state["decode"]["count"],
            "batch_size_min": entry["min"], "batch_size_max": entry["max"],
            "key_averages_enabled": KEY_AVERAGES_ENABLED,
            "key_averages_files": averages or [], "key_averages_error": error,
        }
        (output / f"window-{stage}-TP-{rank}.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    def stop(self, stage=None):
        state = getattr(self, "_bounded_window", None)
        if state is None:
            return old_stop(self, stage)
        active = state["active"]
        if self.profile_in_progress and active:
            profiler = self.torch_profiler
            native_stage = module.ForwardMode.EXTEND if active == "prefill" else module.ForwardMode.DECODE
            result = old_stop(self, native_stage)
            written, error = [], None
            if KEY_AVERAGES_ENABLED and profiler is not None:
                try:
                    averages = profiler.key_averages()
                    rank = module.get_parallel().tp_rank
                    for label, key in (("cpu", "self_cpu_time_total"), ("cuda", "self_cuda_time_total")):
                        path = Path(self.torch_profiler_output_dir) / (
                            f"TP-{rank}.{active}.key-averages-self-{label}.txt")
                        path.write_text(averages.table(sort_by=key, row_limit=100) + "\n", encoding="utf-8")
                        written.append(path.name)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            save(self, active, written, error)
            state["active"] = None
            return result
        # Idempotent barrier after auto-stop; missing/short windows stay visible.
        stages = ("prefill", "decode") if ROLE == "single" else (ROLE,)
        for name in stages:
            path = Path(self.torch_profiler_output_dir) / f"window-{name}-TP-{module.get_parallel().tp_rank}.json"
            if not path.exists():
                save(self, name)
        return module.ProfileReqOutput(success=True, message="Window stopped; validate summaries")

    def predicate(self, batch):
        state = getattr(self, "_bounded_window", None)
        if state is None:
            return old_predicate(self, batch)
        mode = batch.forward_mode
        name = "prefill" if mode.is_prefill() else "decode" if mode.is_decode() else None
        if name is None or (ROLE != "single" and ROLE != name):
            return
        native_count = self.profiler_prefill_ct if name == "prefill" else self.profiler_decode_ct
        target = PREFILL_STEPS if name == "prefill" else DECODE_STEPS
        # Stop the previous stage before accounting the next stage.
        if state["active"] and state["active"] != name and self.profile_in_progress:
            stop(self)
        if native_count < target:
            entry = state[name]
            entry["count"] += 1
            size = batch.batch_size()
            entry["min"] = size if entry["min"] is None else min(entry["min"], size)
            entry["max"] = size if entry["max"] is None else max(entry["max"], size)
            state["active"] = name
        return old_predicate(self, batch)

    cls._init_profile, cls._profile_batch_predicate, cls._stop_profile = init, predicate, stop
    cls._bounded_windows_installed = True
