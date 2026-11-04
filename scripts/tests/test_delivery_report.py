"""Validate standalone report structure without remote execution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "validate_inference_project.py"
spec = importlib.util.spec_from_file_location("report_validator", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class DeliveryReportTests(unittest.TestCase):
    def check(self, content, final=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gpu_model_sglang_single.md"
            path.write_text(content, encoding="utf-8")
            errors = []
            validator.check_delivery_report(path, errors, final=final)
            return errors

    def test_service_only_does_not_require_unrequested_stages(self):
        self.assertEqual(self.check("# title\n## 1. 启动服务\n### 真实对话\n"), [])

    def test_subsections_and_actual_rounds_are_flexible(self):
        self.assertEqual(self.check(
            "# title\n## 1. 启动服务\n### node-a\n"
            "## 2. Baseline压测\n## 3. Profiling\n### Nsys\n"
            "## 4. 优化1：配置与算子\n## 5. 优化2：消融\n"), [])

    def test_baseline_cannot_follow_profiling(self):
        self.assertTrue(self.check(
            "## 1. 启动服务\n## 3. Profiling\n## 2. Baseline压测\n"))

    def test_chat_cannot_be_a_top_level_stage(self):
        self.assertTrue(self.check("## 1. 启动服务\n## 2. 真实对话：node-a\n"))

    def test_optimization_round_cannot_skip_one(self):
        self.assertTrue(self.check("## 1. 启动服务\n## 5. 优化2\n"))

    def test_python_source_is_parsed_without_running_it(self):
        self.assertEqual(self.check(
            "## 1. 启动服务\n```python\nraise RuntimeError('not run')\n```\n"), [])
        self.assertTrue(self.check("## 1. 启动服务\n```python\nif :\n```\n"))

    def test_unclosed_code_block_is_rejected(self):
        self.assertTrue(self.check("## 1. 启动服务\n```bash\necho test\n"))

    def test_final_report_rejects_unresolved_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gpu_model_sglang_single.md"
            path.write_text("## 1. 启动服务\n## 2. Baseline压测\n尚未收到执行结果。\n", encoding="utf-8")
            errors = []
            validator.check_delivery_report(path, errors, final=True)
            self.assertTrue(any("尚未收到" in error for error in errors))

    def test_final_report_rejects_design_table_dump(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gpu_model_sglang_single.md"
            path.write_text("## 1. 启动服务\n#### experiment.toml\n```toml\n[runtime]\n[model]\n[parallelism]\n```\n", encoding="utf-8")
            errors = []
            validator.check_delivery_report(path, errors, final=True)
            self.assertTrue(any("configuration-file dumps" in error for error in errors))

    def test_final_report_rejects_multiline_inline_python(self):
        errors = self.check("## 1. 启动服务\n```bash\n"
                            "docker exec service python3 -P -c '\n"
                            "from pathlib import Path\nprint(Path.cwd())\n'\n```\n", final=True)
        self.assertTrue(any("multiline Python" in error for error in errors))

    def test_final_report_accepts_source_file_and_short_dependency_probe(self):
        self.assertEqual(self.check("## 1. 启动服务\n```bash\n"
                                   "python3 -c 'import torch_npu'\n"
                                   "python3 /client/export_profile.py\n```\n", final=True), [])

    def test_final_report_rejects_preface_and_external_evidence_link(self):
        errors = self.check("# title\n\n本报告由历史实验整理。\n\n## 1. 启动服务\n"
                            "详见[验收](deployment/acceptance.md)。\n", final=True)
        self.assertTrue(any("immediately after its title" in error for error in errors))
        self.assertTrue(any("external document links" in error for error in errors))

    def test_final_report_omits_unstarted_stages_but_accepts_download_commands(self):
        self.assertTrue(self.check("# title\n\n## 1. 启动服务\n"
                                   "## 2. Baseline压测\n未执行。\n", final=True))
        self.assertEqual(self.check("# title\n\n## 1. 启动服务\n```bash\n"
                                   "curl -fL https://example.com/data.json -o /datasets/data.json\n"
                                   "```\n", final=True), [])


if __name__ == "__main__":
    unittest.main()

