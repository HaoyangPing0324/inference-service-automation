"""Reusable Skill sources must not embed one developer workstation."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCOPES = ("SKILL.md", "AGENTS.md", "README.md", "benchmark", "profiling/SKILL.md",
          "multi-agent", "references", "platforms", "scripts")
HOST_SPECIFIC = re.compile(r"(?i)(?:[a-z]:[/\\](?:users|workspace)[/\\]|/home/(?:pinghaoyang|haoyangping)/|/users/pingh/)")


class PortabilityTests(unittest.TestCase):
    def test_reusable_sources_have_no_developer_paths(self):
        violations = []
        for scope in SCOPES:
            path = ROOT / scope
            files = path.rglob("*") if path.is_dir() else [path]
            for file in files:
                if not file.is_file() or file.suffix not in (".md", ".py", ".sh", ".toml", ".env"):
                    continue
                if file.is_relative_to(ROOT / "scripts/tests"):
                    continue
                text = file.read_text(encoding="utf-8")
                if HOST_SPECIFIC.search(text):
                    violations.append(str(file.relative_to(ROOT)))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
