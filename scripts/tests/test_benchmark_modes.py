"""Execute benchmark shell control flow with fake requests, never real services."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROJECTS = [ROOT / "scripts/templates/inference-project",
            ROOT / "scripts/templates/inference-project-pd",
            ROOT / "example/h20/deepseek-v4-flash/sglang/pd-aggregation"]


class BenchmarkModeTests(unittest.TestCase):
    def setUp(self):
        self.bash = os.environ.get("NSYS_TEST_BASH") or shutil.which("bash")
        if not self.bash:
            self.skipTest("Bash unavailable; do not install")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_body(self, project, mode):
        text = (project / "benchmark_test.sh").read_text(encoding="utf-8")
        body = text.split("<<'REMOTE_SCRIPT'\n", 1)[1].rsplit("\nREMOTE_SCRIPT", 1)[0]
        body = body.replace("source /experiment.env", 'source "$1"; shift')
        body = body.replace('/client/results/', self.root.as_posix() + '/results/')
        env = self.root / "fixture.env"
        env.write_text('''CONCURRENCIES=(1 2 4 8 16 32)
BENCHMARK_CMD=(record_run)
BENCHMARK_BASE_ARGS=(--backend test)
SERVICE_PORT=12345
HEALTH_PATH=/health
DATASET_PATH=''
HEALTH_TIMEOUT_SECONDS=1
RESULT_NAME_PREFIX=fixture
ISL=16384
OSL=2048
REQUEST_MULTIPLIER=5
WARMUP_REQUESTS=2
SEED_BASE=20260923
DEVICE_COUNT=8
BENCHMARK_DATASET_PATH_FLAG=--dataset
BENCHMARK_INPUT_LEN_FLAG=--input
BENCHMARK_OUTPUT_LEN_FLAG=--output
BENCHMARK_WARMUP_FLAG=--warmup
BENCHMARK_NUM_PROMPTS_FLAG=--requests
BENCHMARK_CONCURRENCY_FLAG=--concurrency
BENCHMARK_SEED_FLAG=--seed
BENCHMARK_OUTPUT_FILE_FLAG=--file
curl() { return 0; }
python3() { return 0; }
record_run() { printf 'REC'; printf ' %s' "$@"; printf '\\n'; }
''', encoding="utf-8")
        before = env.read_bytes()
        script = self.root / "body.sh"
        script.write_text(body, encoding="utf-8")
        result = subprocess.run([self.bash, script.as_posix(), env.as_posix(), mode],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, env.read_bytes())
        return [line.split() for line in result.stdout.splitlines() if line.startswith("REC ")]

    def test_full_and_tuning_preserve_per_stage_protocol(self):
        for project in PROJECTS:
            with self.subTest(project=project):
                full = self.run_body(project, "full")
                tuning = self.run_body(project, "tuning")
                def values(rows):
                    return {int(row[row.index("--concurrency") + 1]): row for row in rows}
                full, tuning = values(full), values(tuning)
                self.assertEqual(list(full), [1, 2, 4, 8, 16, 32])
                self.assertEqual(list(tuning), [1, 8, 32])
                for concurrency, row in tuning.items():
                    for flag in ("--requests", "--warmup", "--input", "--output", "--seed"):
                        self.assertEqual(row[row.index(flag) + 1], full[concurrency][full[concurrency].index(flag) + 1])
                    self.assertEqual(int(row[row.index("--requests") + 1]), 5 * concurrency)

    def test_invalid_mode_rejected_before_container_access(self):
        for project in PROJECTS:
            text = (project / "benchmark_test.sh").read_text(encoding="utf-8")
            # Only source replacement: missing container settings ensure any container access would fail.
            text = text.replace('source "$ROOT/experiment.env"', "PREFIX_CACHE_MODE=disabled")
            script = self.root / "entry.sh"
            script.write_text(text, encoding="utf-8")
            for args in (["invalid"], ["tuning", "extra"]):
                result = subprocess.run([self.bash, script.as_posix(), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage:", result.stderr)

    def test_all_example_and_template_shell_syntax(self):
        glm = ROOT / "example/h20/glm-v53-flash/sglang/single"
        for project in [*PROJECTS, glm]:
            result = subprocess.run([self.bash, "-n", (project / "benchmark_test.sh").as_posix()], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
