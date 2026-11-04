"""Approved single-service capture control; never installed for PD roles."""
import inspect
import logging
import os

def install(module):
    if os.environ.get("PROFILE_ROLE") != "single":
        return
    cls = module.SchedulerProfilerManager
    if getattr(cls, "_single_stage_targets_installed", False):
        return
    original = cls._init_profile
    original_predicate = cls._profile_batch_predicate
    original_stop = cls._stop_profile
    signature = inspect.signature(original)
    prefix = os.environ.get("PROFILE_PREFIX", "")
    def init(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        selected = bound.arguments.get("profile_prefix") in (
            prefix + "-initial", prefix + "-after-prerun"
        )
        if selected and module.envs.SGLANG_PROFILE_V2.get():
            return module.ProfileReqOutput(success=False, message="Single-stage adapter requires PROFILE_V2=0")
        result = original(*bound.args, **bound.kwargs)
        if result.success:
            self._single_capture_state = None
            if selected:
                self.profiler_target_prefill_ct = int(os.environ["PROFILE_PREFILL_STEPS"])
                self.profiler_target_decode_ct = int(os.environ["PROFILE_DECODE_STEPS"])
                self._single_capture_state = {"phase": "prefill", "active": None, "prefill": 0, "decode": 0}
                logging.getLogger(__name__).info("Single capture armed P=%s D=%s prefix=%s",
                    self.profiler_target_prefill_ct, self.profiler_target_decode_ct,
                    bound.arguments["profile_prefix"])
        return result

    def predicate(self, batch):
        state = getattr(self, "_single_capture_state", None)
        if state is None:
            return original_predicate(self, batch)
        # Predicate runs BEFORE forward. Close a completed capture before the
        # next forward; never overwrite a live profiler on a stage transition.
        if state["active"]:
            stage = state["active"]
            if state[stage] >= getattr(self, "profiler_target_" + stage + "_ct"):
                mode = module.ForwardMode.EXTEND if stage == "prefill" else module.ForwardMode.DECODE
                original_stop(self, stage=mode)
                state["active"] = None
                state["phase"] = "decode" if stage == "prefill" else "done"
        phase = state["phase"]
        if phase == "done":
            return
        mode = batch.forward_mode
        matching = mode.is_prefill() if phase == "prefill" else mode.is_decode()
        if not matching:
            return
        if state["active"] is None:
            result = self._start_profile(mode)
            if result is not None and not result.success:
                raise RuntimeError(result.message)
            state["active"] = phase
        state[phase] += 1
        setattr(self, "profiler_" + phase + "_ct", state[phase])

    def stop(self, stage=None):
        state = getattr(self, "_single_capture_state", None)
        if state is None:
            return original_stop(self, stage=stage)
        if stage is None and state["active"]:
            stage = module.ForwardMode.EXTEND if state["active"] == "prefill" else module.ForwardMode.DECODE
        result = original_stop(self, stage=stage)
        state["active"] = None
        state["phase"] = "done"
        return result
    cls._init_profile = init
    cls._profile_batch_predicate = predicate
    cls._stop_profile = stop
    cls._single_stage_targets_installed = True
