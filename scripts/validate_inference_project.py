#!/usr/bin/env python3
"""Validate an inference experiment scaffold before remote execution."""

from __future__ import annotations

import argparse
import ast
import math
import re
import shlex
import sys
import tomllib
from pathlib import Path


STATIC_FILES = (
    "environment.toml",
    "experiment.toml",
    "experiment.env",
    "benchmark_test.sh",
    "client.sh",
    "LOG.md",
    "server.sh",
    "client/analyze_torch_trace.py",
    "client/chat_test.sh",
    "client/check_profile_window.py",
    "client/parse_bench_result.py",
    "client/profile_capture.sh",
    "client/profile_workload.sh",
    "client/profile_windows.py",
    "client/check_windows.py",
    "client/validate_native_windows.py",
    "client/time_profile.py",
    "client/run_time_profile.py",
    "client/validate_time_window.py",
    "profiling_results/ANALYSIS.md",
    "server/nsys_service.sh",
    "server/nsys_report_ready.sh",
    "server/nsys_stats.sh",
    "server/profile_service.sh",
    "server/service.sh",
    "server/profiling_hooks/sitecustomize.py",
)

DESIGN_REQUIRED_SECTIONS = (
    "runtime",
    "model",
    "parallelism",
    "cache",
    "speculative",
    "memory",
    "workload",
    "profiling",
)
DESIGN_FORBIDDEN_KEYS = {
    "address",
    "container_name",
    "device_ids",
    "gpu_ids",
    "host",
    "ip",
    "model_path",
    "path",
    "pid",
    "port",
    "ssh_target",
    "workspace_dir",
}
REQUIRED_ENV_PATTERNS = {
    "no-prefix baseline": r"(?m)^PREFIX_CACHE_MODE=['\"]?disabled['\"]?$",
    "official reference": r"(?m)^OFFICIAL_REFERENCE_URL=(['\"])[^'\"]+\1$",
    "official version": r"(?m)^OFFICIAL_REFERENCE_VERSION=(['\"])[^'\"]+\1$",
    "official access date": r"(?m)^OFFICIAL_REFERENCE_ACCESSED=(['\"])[^'\"]+\1$",
    "selected SSH targets": r"(?ms)^SSH_TARGETS=\(\s*[^)\s][^)]*\)",
    "official node count": r"(?m)^OFFICIAL_NODE_COUNT=[1-9][0-9]*$",
    "per-host device counts": r"(?m)^HOST_DEVICE_COUNTS=\(\s*[1-9][0-9]*(?:\s+[1-9][0-9]*)*\s*\)$",
    "total device count": r"(?m)^DEVICE_COUNT=[1-9][0-9]*$",
    "profiling TP size": r"(?m)^PROFILE_TP_SIZE=[1-9][0-9]*$",
    "bounded prefill profiling scope": r"(?m)^PROFILE_PREFILL_SCOPE=(['\"])steps\1$",
    "prefill window": r"(?m)^PROFILE_PREFILL_STEPS=4$",
    "decode window": r"(?m)^PROFILE_DECODE_STEPS=128$",
    "profiling request multiplier": r"(?m)^PROFILE_REQUEST_MULTIPLIER=5$",
    "profiling prerun multiplier": r"(?m)^PROFILE_PRERUN_MULTIPLIER=4$",
    "service command": r"(?ms)^SERVICE_CMD=\(\s*[^)\s][^)]*\)",
    "service arguments": r"(?ms)^SERVICE_ARGS=\(\s*[^)\s][^)]*\)",
    "benchmark command": r"(?ms)^BENCHMARK_CMD=\(\s*[^)\s][^)]*\)",
    "server container arguments": r"(?ms)^SERVER_CONTAINER_ARGS=\(\s*[^)\s][^)]*\)",
    "client container arguments": r"(?ms)^CLIENT_CONTAINER_ARGS=\(\s*[^)\s][^)]*\)",
}

def check_delivery_report(path: Path, errors: list[str], final: bool = False) -> None:
    """Check report organization and Python syntax, not runtime correctness."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if final:
        prose = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", text,
                       flags=re.MULTILINE | re.DOTALL)
        intro = prose.split("\n", 1)[1].split("\n## ", 1)[0] if prose.startswith("# ") else ""
        intro = re.sub(r"<!--.*?-->", "", intro, flags=re.DOTALL).strip()
        if intro:
            errors.append("delivery report must start the first workflow stage immediately after its title")
        if re.search(r"\[[^\]]*\]\((?!#)[^)]+\)", prose):
            errors.append("delivery report must stand alone; external document links belong in project evidence")
        if re.search(r"(?m)^(?:状态[：:]\s*)?(?:未执行|尚未执行|待交接)[^\n]*$", prose):
            errors.append("delivery report must omit unstarted stages instead of reserving future status sections")
        for marker in ("<AI:", "NOT_RUN", "待填写", "尚未收到", "尚未交付"):
            if marker in text:
                errors.append(f"delivery report has unresolved status marker {marker}: {path.name}")
        if re.search(r"^#{2,6}[^\n]*(?:experiment\.(?:toml|env)|profile-service\.(?:toml|env))", text, re.MULTILINE):
            errors.append("delivery report must present expanded execution commands, not configuration-file dumps")
        for block in re.findall(r"^```toml\n(.*?)^```", text, re.MULTILINE | re.DOTALL):
            if all(section in block for section in ("[runtime]", "[model]", "[parallelism]")):
                errors.append("delivery report repeats a full internal design table; summarize parameters and expand commands")
        for block in re.findall(r"^```(?:bash|sh|shell)\n(.*?)^```", text, re.MULTILINE | re.DOTALL):
            try:
                tokens = shlex.split(block, comments=True)
            except ValueError:
                continue  # Bash syntax is checked separately; do not guess its grammar.
            for index, token in enumerate(tokens):
                if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", token.rsplit("/", 1)[-1]):
                    continue
                cursor = index + 1
                while cursor < len(tokens) and tokens[cursor].startswith("-"):
                    if tokens[cursor] == "-c":
                        if cursor + 1 < len(tokens) and "\n" in tokens[cursor + 1].strip():
                            errors.append("delivery report embeds multiline Python in a shell command; present a source file and a separate invocation")
                        break
                    cursor += 1
    headings = re.findall(r"^## ([^\n]+)", text, re.MULTILINE)
    core = {"1. 启动服务": 1, "2. Baseline压测": 2, "3. Profiling": 3}
    previous = 0
    optimization = 0
    if not headings or headings[0] != "1. 启动服务":
        errors.append(f"delivery report must begin with service setup: {path.name}")
    for heading in headings:
        if heading in core:
            position = core[heading]
        else:
            match = re.fullmatch(r"(\d+)\. 优化(\d+)(?:[：:].+)?", heading)
            if not match or int(match[2]) != optimization + 1:
                errors.append(f"unexpected or nonsequential report stage: {heading}")
                continue
            optimization += 1
            position = int(match[1])
            if position != optimization + 3:
                errors.append(f"incorrect optimization section number: {heading}")
        if position <= previous:
            errors.append(f"report stages are out of logical order: {heading}")
        previous = position
    fences = re.findall(r"^`{3,}.*$", text, re.MULTILINE)
    if len(fences) % 2:
        errors.append(f"unclosed code fence: {path.name}")
    for index, code in enumerate(re.findall(r"^```python\n(.*?)^\`\`\`", text, re.MULTILINE | re.DOTALL), 1):
        try:
            ast.parse(code)
        except SyntaxError as exc:
            errors.append(f"invalid report Python block {index}: {exc.msg}")


def is_generated_result(path: Path, project: Path) -> bool:
    relative = path.relative_to(project)
    if relative.parts[:2] == ("client", "results"):
        return True
    return relative.parts[0] == "profiling_results" and relative.name != "ANALYSIS.md"


def is_active_source(path: Path, project: Path) -> bool:
    """Bootstrap templates and historical study snapshots are not live inputs."""
    relative = path.relative_to(project)
    return (path.is_file() and not is_generated_result(path, project)
            and relative.parts[0] not in ("coordination", "tuning")
            and "__pycache__" not in relative.parts)


def walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def validate_design(path: Path, env: str, errors: list[str]) -> None:
    try:
        with path.open("rb") as stream:
            design = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"invalid experiment.toml: {exc}")
        return
    if design.get("version") != 1:
        errors.append("experiment.toml must contain version = 1")
    for section in DESIGN_REQUIRED_SECTIONS:
        if not isinstance(design.get(section), dict):
            errors.append(f"experiment.toml missing [{section}]")
    forbidden = sorted(set(walk_keys(design)) & DESIGN_FORBIDDEN_KEYS)
    if forbidden:
        errors.append("experiment.toml contains runtime wiring field(s): " + ", ".join(forbidden))
    parallelism = design.get("parallelism") or {}
    workload = design.get("workload") or {}
    profiling = design.get("profiling") or {}
    protocol = profiling.get("protocol", "steps")
    cache = design.get("cache") or {}
    speculative = design.get("speculative") or {}
    for label, value in (
        ("parallelism.tensor_parallel_size", parallelism.get("tensor_parallel_size")),
        ("parallelism.total_devices", parallelism.get("total_devices")),
        ("workload.input_length", workload.get("input_length")),
        ("workload.output_length", workload.get("output_length")),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"experiment.toml {label} must be a positive integer")
    if protocol == "steps" and profiling.get("prefill_scope") != "steps":
        errors.append("experiment.toml profiling.prefill_scope must be 'steps'")
    legacy = (("prefill_steps", 4), ("decode_steps", 128),
              ("request_multiplier", 5), ("prerun_multiplier", 4)) if protocol == "steps" else ()
    for key, expected in (*legacy, ("warmup_requests", 2)):
        if profiling.get(key) != expected:
            errors.append(f"experiment.toml profiling.{key} must be {expected}")
    if protocol not in ("time", "steps"):
        errors.append("profiling.protocol must be time or steps")
    if protocol == "time":
        for key in ("prerun_seconds", "capture_seconds"):
            value = profiling.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 or (key == "capture_seconds" and value == 0)):
                errors.append(f"profiling.{key} must be finite and {'positive' if key == 'capture_seconds' else 'nonnegative'}")
        budget = profiling.get("max_requests")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
            errors.append("profiling.max_requests must be a positive integer")
        for key in ("prerun_completed_multiplier", "postrun_completed_multiplier"):
            value = profiling.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                errors.append(f"profiling.{key} must be a positive integer")
        for key in ("protocol", "prerun_seconds", "capture_seconds", "max_requests",
                    "prerun_completed_multiplier", "postrun_completed_multiplier"):
            match = re.search(rf"(?m)^PROFILE_{key.upper()}=(.+)$", env)
            if not match:
                errors.append(f"Missing PROFILE_{key.upper()}")
            elif str(profiling.get(key)) != match[1].strip().strip("'\""):
                try:
                    same = key != "protocol" and float(profiling[key]) == float(match[1])
                except (ValueError, TypeError):
                    same = False
                if not same:
                    errors.append(f"experiment.toml differs from experiment.env for PROFILE_{key.upper()}")
    if not isinstance(cache.get("prefix_cache_enabled"), bool):
        errors.append("experiment.toml cache.prefix_cache_enabled must be boolean")
    if not isinstance(speculative.get("enabled"), bool):
        errors.append("experiment.toml speculative.enabled must be boolean")
    elif speculative.get("enabled"):
        if not isinstance(speculative.get("algorithm"), str) or not speculative["algorithm"].strip():
            errors.append("enabled speculative decoding requires speculative.algorithm")
        if not isinstance(speculative.get("draft_model"), str) or not speculative["draft_model"].strip():
            errors.append("enabled speculative decoding requires speculative.draft_model")

    comparisons = (
        ("PROFILE_TP_SIZE", parallelism.get("tensor_parallel_size")),
        ("DEVICE_COUNT", parallelism.get("total_devices")),
        ("ISL", workload.get("input_length")),
        ("OSL", workload.get("output_length")),
        ("PROFILE_DECODE_STEPS", profiling.get("decode_steps")),
        ("PROFILE_PREFILL_STEPS", profiling.get("prefill_steps")),
    )
    for env_key, design_value in comparisons:
        match = re.search(rf"(?m)^{env_key}=([0-9]+)$", env)
        if match and isinstance(design_value, int) and int(match.group(1)) != design_value:
            errors.append(f"experiment.toml differs from experiment.env for {env_key}")
    prefix_mode = re.search(r"(?m)^PREFIX_CACHE_MODE=(['\"]?)(enabled|disabled)\1$", env)
    if prefix_mode and isinstance(cache.get("prefix_cache_enabled"), bool):
        expected = "enabled" if cache["prefix_cache_enabled"] else "disabled"
        if prefix_mode.group(2) != expected:
            errors.append("experiment.toml differs from experiment.env for prefix cache")


def environment_location_matches(project: Path, server: dict, entry: dict, *, remote_layout=False) -> bool:
    identity = (server.get("alias"), entry.get("model_name"), entry.get("framework"), entry.get("deployment"))
    if not all(isinstance(value, str) and value for value in identity):
        return False
    if remote_layout:
        workspace = entry.get("workspace_dir")
        return isinstance(workspace, str) and project == (Path(workspace) / "_".join(identity)).resolve()
    return project.parts[-4:] == identity


def validate_deployment(project: Path, *, remote_layout=False) -> list[str]:
    """Only the files and explicit configuration needed by startup/chat.

    Future benchmark/profiling defaults, result reports and placeholders are
    intentionally outside this stage. Runtime errors drive further diagnosis.
    """
    errors = []
    for name in ("environment.toml", "experiment.env", "server.sh", "server/service.sh", "client.sh", "client/chat_test.sh"):
        if not (project / name).is_file():
            errors.append(f"missing deployment file: {name}")
    environment = project / "environment.toml"
    if environment.is_file():
        try:
            config = tomllib.loads(environment.read_text(encoding="utf-8"))
            server, entry = config.get("server", {}), config.get("project", {})
            if not environment_location_matches(project, server, entry, remote_layout=remote_layout):
                errors.append("experiment directory identity differs from environment.toml")
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"invalid environment.toml: {exc}")
    env_path = project / "experiment.env"
    if env_path.is_file():
        env = env_path.read_text(encoding="utf-8")
        for label in ("no-prefix baseline", "selected SSH targets", "service command", "service arguments",
                      "server container arguments", "client container arguments"):
            if not re.search(REQUIRED_ENV_PATTERNS[label], env):
                errors.append(f"experiment.env missing {label}")
        # Check only startup values, not future workload/capture placeholders.
        for match in re.finditer(r"(?ms)^(?:SERVICE_CMD|SERVICE_ARGS|SSH_TARGETS|CONTAINER_CLI|SERVER_CONTAINER_ARGS|CLIENT_CONTAINER_ARGS|PREFIX_CACHE_DISABLE_ARGS)=\([^)]*\)|^(?:MODEL_PATH|IMAGE|[A-Z_]*CONTAINER_NAME)=[^\n]*", env):
            if re.search(r"\{\{[A-Z0-9_]+\}\}|<AI:[^>]+>|TODO", match[0]):
                errors.append("unresolved deployment command/path placeholder")
        default_disabled = bool(re.search(r"(?m)^PREFIX_CACHE_DEFAULT_DISABLED=['\"]?1['\"]?$", env))
        disable_args = bool(re.search(r"(?ms)^PREFIX_CACHE_DISABLE_ARGS=\(\s*[^)\s][^)]*\)", env))
        if not default_disabled and not disable_args:
            errors.append("no-prefix startup lacks disable arguments or disabled framework default")
    design = project / "experiment.toml"
    if design.is_file():
        try:
            data = tomllib.loads(design.read_text(encoding="utf-8"))
            if data.get("cache", {}).get("prefix_cache_enabled") is True:
                errors.append("deployment design conflicts with disabled prefix cache")
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"invalid experiment.toml: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--scaffold", action="store_true", help="Check generated structure before filling values")
    parser.add_argument("--stage", choices=("deployment", "all"), default="all",
                        help="Deployment checks only startup/chat, not future workload/profiling or final reports")
    parser.add_argument("--remote", action="store_true", help="Validate the configured remote workspace_dir/title layout")
    args = parser.parse_args()
    project = args.project.resolve()
    errors: list[str] = []
    if args.stage == "deployment":
        errors = validate_deployment(project, remote_layout=args.remote)
        for error in errors:
            print(error, file=sys.stderr)
        if not errors:
            print("Deployment inputs valid; future stages were not checked")
        return int(bool(errors))

    title = "_".join(project.parts[-4:]) if len(project.parts) >= 4 else ""
    if args.remote and (project / "environment.toml").is_file():
        try:
            config = tomllib.loads((project / "environment.toml").read_text(encoding="utf-8"))
            title = "_".join((config["server"]["alias"], config["project"]["model_name"], config["project"]["framework"], config["project"]["deployment"]))
        except (KeyError, TypeError, OSError, tomllib.TOMLDecodeError):
            errors.append("invalid remote experiment identity")
    required = list(STATIC_FILES)
    server_entry = project / "server.sh"
    uses_overrides = server_entry.is_file() and "server/source_overrides/load.sh" in server_entry.read_text(encoding="utf-8")
    if uses_overrides or (project / "server/source_overrides").is_dir():
        required.extend(("run_source_variant.sh", "server/source_overrides/load.sh", "server/source_overrides/manifest.env"))
    required.append(f"{title}.md")
    for relative in required:
        if not (project / relative).is_file():
            errors.append(f"missing file: {relative}")
    environment_path = project / "environment.toml"
    if environment_path.is_file():
        try:
            with environment_path.open("rb") as stream:
                environment = tomllib.load(stream)
            server = environment.get("server", {})
            entry = environment.get("project", {})
            if not environment_location_matches(project, server, entry, remote_layout=args.remote):
                errors.append("experiment directory identity differs from environment.toml")
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"invalid experiment-local environment.toml: {exc}")
    # Historical adapter sources may remain as examples, but native execution
    # must not require or silently enable them.

    check_delivery_report(project / f"{title}.md", errors, final=not args.scaffold)

    if not args.scaffold:
        text_files = [
            path
            for path in project.rglob("*")
            if is_active_source(path, project)
        ]
        for path in text_files:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            leftovers = re.findall(r"\{\{[A-Z0-9_]+\}\}|<AI:[^>]+>|TODO", text)
            if leftovers:
                errors.append(f"unresolved placeholder in {path.relative_to(project)}: {leftovers[0]}")

    env_path = project / "experiment.env"
    if env_path.is_file() and not args.scaffold:
        env = env_path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^PROFILE_HOOK_ENABLED=0$", env):
            errors.append("native profiling requires PROFILE_HOOK_ENABLED=0; adapters require explicit approval")
        for label, pattern in REQUIRED_ENV_PATTERNS.items():
            if re.search(r"(?m)^PROFILE_PROTOCOL=['\"]?time['\"]?$", env) and label in (
                "bounded prefill profiling scope", "prefill window", "decode window",
                "profiling request multiplier", "profiling prerun multiplier"):
                continue
            if not re.search(pattern, env):
                errors.append(f"experiment.env missing {label}")
        node_match = re.search(r"(?m)^OFFICIAL_NODE_COUNT=([1-9][0-9]*)$", env)
        counts_match = re.search(r"(?m)^HOST_DEVICE_COUNTS=\(\s*([1-9][0-9]*(?:\s+[1-9][0-9]*)*)\s*\)$", env)
        total_match = re.search(r"(?m)^DEVICE_COUNT=([1-9][0-9]*)$", env)
        if node_match and counts_match and total_match:
            host_counts = [int(value) for value in counts_match.group(1).split()]
            if len(host_counts) != int(node_match.group(1)):
                errors.append("HOST_DEVICE_COUNTS length differs from OFFICIAL_NODE_COUNT")
            if sum(host_counts) != int(total_match.group(1)):
                errors.append("DEVICE_COUNT differs from sum(HOST_DEVICE_COUNTS)")
        default_disabled = bool(re.search(r"(?m)^PREFIX_CACHE_DEFAULT_DISABLED=['\"]?1['\"]?$", env))
        disable_args = bool(re.search(r"(?ms)^PREFIX_CACHE_DISABLE_ARGS=\(\s*[^)\s][^)]*\)", env))
        evidence = bool(re.search(r"(?m)^PREFIX_CACHE_EVIDENCE=(['\"])[^'\"]+\1$", env))
        if not evidence or (not default_disabled and not disable_args):
            errors.append("no-prefix baseline lacks verified disable args/default evidence")
        design_path = project / "experiment.toml"
        if design_path.is_file():
            validate_design(design_path, env, errors)

    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Validation passed: {project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
