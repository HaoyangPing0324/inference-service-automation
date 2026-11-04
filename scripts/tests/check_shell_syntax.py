#!/usr/bin/env python3
"""Check maintained Bash scripts and fenced commands without executing them."""
import argparse
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bash", required=True, help="An already installed Bash executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    count = 0
    errors = []
    for base in (root / "scripts/templates", root / "example"):
        for file in sorted(base.rglob("*")):
            if not file.is_file() or file.suffix not in (".sh", ".md"):
                continue
            source = file.read_text(encoding="utf-8")
            chunks = [source] if file.suffix == ".sh" else re.findall(
                r"^```(?:bash|sh|shell)\s*\n(.*?)^```", source, re.MULTILINE | re.DOTALL)
            for i, chunk in enumerate(chunks):
                result = subprocess.run([args.bash, "--noprofile", "--norc", "-n"],
                                        input=chunk, capture_output=True, text=True, encoding="utf-8")
                count += 1
                if result.returncode:
                    errors.append(f"{file.relative_to(root)} block {i}: {result.stderr.strip()}")
    print(f"Checked {count} Bash scripts/command blocks")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
