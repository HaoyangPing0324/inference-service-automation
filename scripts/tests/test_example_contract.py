"""Example projects must remain coherent, lightweight and non-executing references."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = (
    ROOT / "example/h20/glm-v53-flash/sglang/single",
    ROOT / "example/h20/deepseek-v4-flash/sglang/pd-aggregation",
)
spec = importlib.util.spec_from_file_location("example_project_validator", ROOT / "scripts/validate_inference_project.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ExampleContractTests(unittest.TestCase):
    def test_shared_execution_protocols_remain_in_sync(self):
        for project, kind in zip(PROJECTS, ("inference-project", "inference-project-pd")):
            for rel in ("server.sh", "client.sh", "benchmark_test.sh",
                        "client/profile_workload.sh", "client/profile_windows.py",
                        "client/validate_native_windows.py", "server/service.sh",
                        "client/time_profile.py", "client/run_time_profile.py", "client/validate_time_window.py",
                        "server/profile_service.sh", "server/nsys_service.sh",
                        "server/nsys_report_ready.sh", "server/source_overrides/load.sh"):
                with self.subTest(project=project, file=rel):
                    self.assertEqual((project / rel).read_text(encoding="utf-8").rstrip(),
                                     (ROOT / "scripts/templates" / kind / rel).read_text(encoding="utf-8").rstrip())
            self.assertEqual((project / "client/analyze_torch_trace.py").read_text(encoding="utf-8"),
                             (ROOT / "scripts/templates/shared/client/analyze_torch_trace.py").read_text(encoding="utf-8"))

    def test_glm_chat_rejects_wrong_model_or_empty_content_without_network(self):
        script = PROJECTS[0] / "client/chat_test.py"
        cases = (
            ({"model": "glm-53-flash", "choices": [{"message": {"content": "Hello"}}]}, True),
            ({"model": "wrong", "choices": [{"message": {"content": "Hello"}}]}, False),
            ({"model": "glm-53-flash", "choices": [{"message": {"content": ""}}]}, False),
        )
        for response, valid in cases:
            with self.subTest(response=response), \
                 patch.object(sys, "argv", [str(script), "30000", "glm-53-flash"]), \
                 patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())), \
                 contextlib.redirect_stdout(io.StringIO()):
                if valid:
                    runpy.run_path(str(script), run_name="__main__")
                else:
                    with self.assertRaises(RuntimeError):
                        runpy.run_path(str(script), run_name="__main__")

    def test_both_scaffolds_have_current_structure(self):
        for project in PROJECTS:
            with self.subTest(project=project):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/validate_inference_project.py"), str(project), "--scaffold"],
                    capture_output=True, text=True, encoding="utf-8",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((project / "tuning/templates").exists())
                if project.name == "single":
                    self.assertFalse((project / "tuning").exists())
                self.assertFalse(list(project.glob("*_deployment.md")))
                self.assertFalse(list(project.glob("*_profiling.md")))

    def test_designs_have_no_default_markers_or_runtime_wiring(self):
        for project in PROJECTS:
            with self.subTest(project=project):
                text = (project / "experiment.toml").read_text(encoding="utf-8")
                data = tomllib.loads(text)
                self.assertNotIn("framework-default", text)
                self.assertTrue(set(validator.DESIGN_REQUIRED_SECTIONS).issubset(data))
                self.assertFalse(set(validator.walk_keys(data)) & validator.DESIGN_FORBIDDEN_KEYS)
                self.assertEqual(data["cache"]["prefix_cache_enabled"], False)
                self.assertEqual(data["profiling"]["protocol"], "time")
                self.assertEqual(data["profiling"]["prerun_completed_multiplier"], 4)
                self.assertEqual(data["profiling"]["postrun_completed_multiplier"], 1)
                self.assertEqual(data["workload"]["concurrencies"], [1, 2, 4, 8, 16, 32])
                errors = []
                validator.validate_design(project / "experiment.toml",
                                          (project / "experiment.env").read_text(encoding="utf-8"), errors)
                self.assertEqual(errors, [])

    def test_reports_and_python_sources_parse_without_running_them(self):
        for project in PROJECTS:
            title = "_".join(project.parts[-4:])
            report = project / (title + ".md")
            errors = []
            validator.check_delivery_report(report, errors, final=True)
            self.assertEqual(errors, [])
            for path in project.rglob("*.py"):
                ast.parse(path.read_text(encoding="utf-8"))
            for path in project.rglob("*.md"):
                text = path.read_text(encoding="utf-8")
                text = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", text,
                              flags=re.MULTILINE | re.DOTALL)
                for _, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text):
                    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                        continue
                    self.assertTrue((path.parent / target.split("#", 1)[0]).exists(),
                                    f"broken link in {path}: {target}")

    def test_result_payloads_are_only_explicit_placeholders(self):
        for project in PROJECTS:
            self.assertFalse(list(project.rglob("*.trace.json.gz")))
            self.assertFalse(list(project.rglob("*.nsys-rep")))
            for path in project.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    self.assertLess(path.stat().st_size, 256 * 1024, str(path))

    def test_current_example_results_use_one_middle_window(self):
        for project in PROJECTS:
            roles = ("single",) if project.name == "single" else ("prefill", "decode")
            results = project / "profiling_results"
            for tool in ("profiler", "nsys"):
                for c in ("C1",) if project.name == "single" else ("C1", "C16"):
                    current = results / tool / c
                    self.assertTrue((current / "capture").is_dir())
                    self.assertFalse((current / "initial").exists())
                    self.assertFalse((current / "after-prerun").exists())
                    for role in roles:
                        self.assertTrue((current / "capture" / role).is_dir())
            self.assertFalse((results / "legacy-steps").exists())

    def test_example_root_contains_only_complete_h20_projects(self):
        self.assertEqual({path.name for path in (ROOT / "example").iterdir()}, {"h20"})
        for project in PROJECTS:
            report = project / ("_".join(project.parts[-4:]) + ".md")
            text = report.read_text(encoding="utf-8")
            self.assertNotIn("以下为历史steps", text)
            self.assertNotIn("legacy-steps", text)
            self.assertIn("/client/run_time_profile.py", text)

    def test_joint_source_review_matches_executed_report_sources(self):
        project = PROJECTS[1]
        study = project / "tuning/20261021-joint-c1-c8-c32"
        report = (project / "h20_deepseek-v4-flash_sglang_pd-aggregation.md").read_text(encoding="utf-8")
        prepare = re.search(r"保存为 `[^`]+/client/prepare_sources.py`：\s*```python\n(.*?)^```", report, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(prepare)
        found = []
        for node in ast.walk(ast.parse(prepare[1])):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "replace_source":
                continue
            destination = ast.literal_eval(node.args[1])
            if not destination.startswith("/candidate/"):
                continue
            relative = destination.removeprefix("/candidate/")
            expected = ast.literal_eval(node.args[3])
            original = ast.literal_eval(node.args[2])
            self.assertEqual(hashlib.sha256((study / "baseline/source" / relative).read_bytes()).hexdigest(), original)
            self.assertEqual(hashlib.sha256((study / "source" / relative).read_bytes()).hexdigest(), expected)
            found.append(relative)
        self.assertEqual(set(found), {"framework/deepseek_v4.py", "operators/elementwise.py"})
        operator = re.search(r"保存为 `[^`]+/source/operators/grouped_rmsnorm.py`：\s*```python\n(.*?)^```", report, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(operator)
        self.assertEqual(ast.dump(ast.parse(operator[1])),
                         ast.dump(ast.parse((study / "source/operators/grouped_rmsnorm.py").read_text(encoding="utf-8"))))
        parameters = tomllib.loads((study / "experiment.toml").read_text(encoding="utf-8"))
        self.assertEqual(parameters["cache"]["chunked_prefill_size"], 8192)
        self.assertEqual(parameters["memory"]["prefill_static_fraction"], .88)
        self.assertEqual(parameters["memory"]["decode_static_fraction"], .80)
        self.assertNotIn("profiling", parameters)
        self.assertTrue((study / "修改说明.md").is_file())
        self.assertFalse((study / "baseline/benchmark").exists())
        self.assertFalse((study / "candidates").exists())
        self.assertFalse((study / "baseline/source/operators/grouped_rmsnorm.py").exists())
        self.assertEqual({p.relative_to(study / "source").as_posix() for p in (study / "source").rglob("*.py")},
                         {"framework/deepseek_v4.py", "operators/elementwise.py", "operators/grouped_rmsnorm.py"})

    def test_reports_define_every_invoked_custom_python_script(self):
        for project in PROJECTS:
            report = project / ("_".join(project.parts[-4:]) + ".md")
            text = report.read_text(encoding="utf-8")
            defined = {Path(path).name for path in re.findall(r"保存为 `([^`]+)`", text)}
            calls = re.findall(r"python3?\s+(?:-[Piu]\s+)*(/[^\s]+\.py)", text)
            self.assertTrue(calls)
            self.assertEqual([path for path in calls if Path(path).name not in defined], [])
            self.assertIn("保存为 `/srv/inference/", text)
            self.assertNotIn("PD需先将客户端workload.json复制", text)
            if project.name != "single":
                title = "_".join(project.parts[-4:])
                source = f"/srv/inference/{title}/server/profiles/example-time-torch-C16/workload.json"
                self.assertIn(f"scp {source} decode-node:{source}", text)
                self.assertIn(f"scp /srv/inference/{title}/client/validate_time_window.py", text)

    def test_linux_configs_resolve_locally_without_docker_or_ssh(self):
        bash = os.environ.get("NSYS_TEST_BASH") or shutil.which("bash")
        if not bash:
            self.skipTest("Existing Bash unavailable; no tool installation")
        for project in PROJECTS:
            config = project / "experiment.env"
            result = subprocess.run(
                [bash, "--noprofile", "--norc", "-c",
                 'source "$1"; printf "%s\\n" "$MODEL_PATH" "$PROFILE_HOOK_ENABLED" '
                 '"$PROFILE_PREFILL_STEPS" "$PROFILE_DECODE_STEPS" "$PREFIX_CACHE_MODE" '
                 '"${CONCURRENCIES[*]}" "${PREFIX_CACHE_DISABLE_ARGS[*]}" '
                 '"${PROFILE_SINGLE_STAGE_ADAPTER_APPROVED:-0}"',
                 "bash", config.as_posix()],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            values = result.stdout.splitlines()
            self.assertTrue(values[0].startswith("/models/"))
            self.assertEqual(values[1:], ["0", "4", "128", "disabled",
                                         "1 2 4 8 16 32", "--disable-radix-cache", "0"])


if __name__ == "__main__":
    unittest.main()
