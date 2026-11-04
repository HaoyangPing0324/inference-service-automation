#!/usr/bin/env python3
"""Create a reproducible inference-service experiment from environment.toml."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import posixpath
import re
import shutil
import sys
import tomllib
from pathlib import Path


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
CONTAINER_MODELS_DIR = "/models"
REQUIRED_SERVER = ("type", "alias", "operations_command")
REQUIRED_PROJECT = (
    "workspace_dir",
    "host_models_dir",
    "model_path",
    "model_name",
    "framework",
    "deployment",
)


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"Error: {message}")


def require_text(section: dict, keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if not isinstance(section.get(key), str) or not section[key].strip()]
    if missing:
        fail(f"{label} is missing non-empty field(s): {', '.join(missing)}")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def render_text(text: str, tokens: dict[str, str], source: Path) -> str:
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", value)
    leftovers = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", text)))
    if leftovers:
        fail(f"unresolved token(s) in {source}: {', '.join(leftovers)}")
    return text


def identity_parts(server: dict, project: dict) -> tuple[str, str, str, str]:
    return server["alias"], project["model_name"], project["framework"], project["deployment"]


def check_config_location(path: Path, parts: tuple[str, str, str, str], remote_project: str | None = None) -> None:
    if remote_project is not None:
        if path.name != "environment.toml" or path.parent != Path(remote_project).resolve():
            fail("remote environment.toml must be exactly workspace_dir/title/environment.toml")
        return
    if path.name != "environment.toml" or path.parent.parts[-4:] != parts:
        fail(
            "environment.toml must be inside <workspace>/<hardware>/<model>/<framework>/<deployment>/; "
            "its last four directory names must match the configuration. "
            "Initialize the experiment directory first; do not use a shared workspace-root config."
        )


def inventory_server(workspace: Path, alias: str, hardware_type: str | None) -> dict | None:
    """Select only the already-confirmed exact alias; never guess from resources."""
    path = workspace / "servers.toml"
    if not path.exists():
        return None  # Legacy/manual experiment initialization remains supported.
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    entries = data.get("servers")
    if data.get("version") != 1 or not isinstance(entries, list) or not entries:
        fail("servers.toml requires version = 1 and non-empty [[servers]] entries")
    aliases = []
    for entry in entries:
        if not isinstance(entry, dict):
            fail("each servers.toml entry must be a table")
        require_text(entry, REQUIRED_SERVER, "[[servers]]")
        key = entry["alias"]
        if not SLUG_RE.fullmatch(key):
            fail("servers[].alias must be a valid directory alias")
        aliases.append(key)
        hosts = entry.get("hosts")
        if not isinstance(hosts, list) or not hosts:
            fail(f"servers[{key}].hosts must contain at least one candidate")
        names = []
        for host in hosts:
            if not isinstance(host, dict):
                fail(f"servers[{key}].hosts entries must be tables")
            require_text(host, ("name", "address"), f"servers[{key}].hosts")
            if "device_count" in host:
                fail("inventory hosts must not specify device_count")
            names.append(host["name"].strip())
        if len(names) != len(set(names)):
            fail(f"duplicate host names in servers[{key}]")
    if len(aliases) != len(set(aliases)):
        fail("servers.toml aliases must be unique")
    selected = next((entry for entry in entries if entry["alias"] == alias), None)
    if selected is None:
        fail(f"no inventory entry for confirmed alias {alias!r}; ask the user to select or add it")
    if hardware_type and selected["type"] != hardware_type:
        fail("--hardware-type conflicts with the selected inventory entry; ask before changing it")
    return selected


def initialize_config(args: argparse.Namespace) -> int:
    parts = (args.hardware, args.model, args.framework, args.deployment)
    if not all(parts):
        fail("--init requires confirmed --hardware, --model, --framework and --deployment")
    for value in parts:
        if not SLUG_RE.fullmatch(value):
            fail(f"experiment directory component must match {SLUG_RE.pattern!r}; got {value!r}")
    target = args.workspace.resolve().joinpath(*parts)
    config = target / "environment.toml"
    if config.exists():
        with config.open("rb") as stream:
            existing = tomllib.load(stream)
        try:
            existing_parts = identity_parts(existing.get("server", {}), existing.get("project", {}))
        except KeyError:
            fail("existing experiment config is missing identity fields; preserve and repair it first")
        if existing_parts != parts:
            fail("existing experiment config disagrees with the requested identity; it was not overwritten")
        print(config)
        return 0
    template = Path(__file__).resolve().parent.parent / "environment.toml"
    selected = inventory_server(args.workspace.resolve(), args.hardware, args.hardware_type)
    text = template.read_text(encoding="utf-8")
    replacements = {
        "type": args.hardware_type or "",
        "alias": args.hardware,
        "model_name": args.model,
        "framework": args.framework,
        "deployment": args.deployment,
    }
    for key, value in replacements.items():
        text, count = re.subn(
            rf'(?m)^{key} = ""$',
            lambda _match: f"{key} = {json.dumps(value, ensure_ascii=False)}",
            text,
        )
        if count != 1:
            fail(f"initialization template must contain exactly one empty {key} field")
    if selected is not None:
        # Preserve the project-side fill-in form and replace only the server table.
        server_lines = ["[server]"]
        for key in REQUIRED_SERVER:
            server_lines.append(f"{key} = {json.dumps(selected[key], ensure_ascii=False)}")
        for host in selected["hosts"]:
            server_lines.extend(["", "[[server.hosts]]"])
            for key in ("name", "address"):
                server_lines.append(f"{key} = {json.dumps(host[key], ensure_ascii=False)}")
        start, end = text.index("[server]"), text.index("[project]")
        text = text[:start] + "\n".join(server_lines) + "\n\n" + text[end:]
    target.mkdir(parents=True, exist_ok=True)
    with config.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    print(config)
    return 0


def load_config(path: Path, *, remote_layout: bool = False) -> tuple[dict, dict, list[dict]]:
    if path == Path(__file__).resolve().parent.parent / "environment.toml":
        fail("the Skill-root environment.toml is an initialization template, not an experiment config")
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if data.get("version") != 1:
        fail("environment.toml must contain version = 1")
    server = data.get("server") or {}
    project = data.get("project") or {}
    require_text(server, REQUIRED_SERVER, "[server]")
    require_text(project, REQUIRED_PROJECT, "[project]")
    legacy_container_root = project.get("container_models_dir", "")
    if legacy_container_root not in ("", CONTAINER_MODELS_DIR):
        fail(
            "project.container_models_dir is fixed to /models; "
            "remove this legacy field from environment.toml"
        )
    legacy_output_root = project.get("output_root", "")
    if legacy_output_root not in (None, ""):
        fail(
            "project.output_root is not configurable; keep environment.toml "
            "inside its experiment directory and remove this legacy field"
        )
    model_path = project["model_path"].rstrip("/")
    if model_path != CONTAINER_MODELS_DIR and not model_path.startswith(CONTAINER_MODELS_DIR + "/"):
        fail("project.model_path must be /models or a path below /models/")
    hosts = server.get("hosts") or []
    if not isinstance(hosts, list) or not hosts:
        fail("define at least one [[server.hosts]] entry")
    for index, host in enumerate(hosts, start=1):
        require_text(host, ("name", "address"), f"[[server.hosts]] #{index}")
        if "device_count" in host:
            fail(
                f"[[server.hosts]] #{index}.device_count is no longer configurable; "
                "remove it because device topology is derived from the official tutorial"
            )
    host_names = [host["name"].strip() for host in hosts]
    duplicate_names = sorted({name for name in host_names if host_names.count(name) > 1})
    if duplicate_names:
        fail("server.hosts[].name must be unique; duplicate(s): " + ", ".join(duplicate_names))
    for key, value in (
        ("server.alias", server["alias"]),
        ("project.model_name", project["model_name"]),
        ("project.framework", project["framework"]),
        ("project.deployment", project["deployment"]),
    ):
        if not SLUG_RE.fullmatch(value):
            fail(f"{key} must match {SLUG_RE.pattern!r}; got {value!r}")
    parts = identity_parts(server, project)
    remote_project = posixpath.join(project["workspace_dir"].rstrip("/"), "_".join(parts)) if remote_layout else None
    check_config_location(path, parts, remote_project)
    return server, project, hosts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("environment.toml"))
    parser.add_argument("--init", action="store_true", help="Create only an experiment-local environment.toml")
    parser.add_argument("--workspace", type=Path, help="Workspace containing the hardware/model/framework/method directories")
    parser.add_argument("--hardware", help="Confirmed hardware directory alias")
    parser.add_argument("--hardware-type", help="Confirmed full hardware name, if already known")
    parser.add_argument("--model", help="Confirmed model directory name")
    parser.add_argument("--framework", help="Confirmed inference framework")
    parser.add_argument("--deployment", help="Confirmed deployment method")
    parser.add_argument("--dry-run", action="store_true", help="Print the target without writing files")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--remote", action="store_true", help="Generate directly at configured remote workspace_dir/title")
    modes.add_argument("--local-scaffold", action="store_true", help="Explicit offline template/example maintenance only; not normal deployment")
    args = parser.parse_args()
    if args.init:
        if args.workspace is None or args.dry_run or args.remote or args.local_scaffold:
            fail("--init requires --workspace and cannot be combined with --dry-run")
        return initialize_config(args)
    if not args.remote and not args.local_scaffold:
        fail("actual experiments generate on the target server with --remote; use --local-scaffold only for offline maintenance")
    if any(value is not None for value in (
        args.workspace, args.hardware, args.hardware_type, args.model, args.framework, args.deployment
    )):
        fail("identity/workspace arguments are only used with --init; generate with --config afterwards")

    config = args.config.resolve()
    server, project, hosts = load_config(config, remote_layout=args.remote)
    title = "_".join(identity_parts(server, project))
    target = config.parent
    allowed_existing = {"environment.toml", "experiment.toml", "LOG.md", "coordination"}
    unexpected = [path.name for path in target.iterdir() if path.name not in allowed_existing]
    if unexpected:
        fail(f"target contains existing project content; refusing to overwrite: {target}")

    remote_project = posixpath.join(project["workspace_dir"].rstrip("/"), title)
    hook_family = project["model_name"].split("-", 1)[0].replace(".", "_")
    hook_module = f"{hook_family}_decode_window"
    deployment_heading = {
        "single": "Single Node Deployment",
        "dual": "Dual Node Deployment",
        "pd": "PD Deployment",
    }.get(project["deployment"], f"{project['deployment']} Deployment")
    available_ssh_targets = " ".join(shell_quote(host["address"]) for host in hosts)
    tokens = {
        "TITLE": title,
        "TITLE_SH": shell_quote(title),
        "HARDWARE_ALIAS_SH": shell_quote(server["alias"]),
        "HARDWARE_TYPE_SH": shell_quote(server["type"]),
        "OPERATIONS_COMMAND_SH": shell_quote(server["operations_command"]),
        "AVAILABLE_SSH_TARGETS": available_ssh_targets,
        "MODEL_NAME_SH": shell_quote(project["model_name"]),
        "MODEL_PATH_SH": shell_quote(project["model_path"]),
        "SERVED_MODEL_NAME_SH": shell_quote(project["model_name"]),
        "FRAMEWORK_SH": shell_quote(project["framework"]),
        "DEPLOYMENT_SH": shell_quote(project["deployment"]),
        "DEPLOYMENT_HEADING": deployment_heading,
        "WORKSPACE_DIR_SH": shell_quote(project["workspace_dir"]),
        "REMOTE_PROJECT_DIR_SH": shell_quote(remote_project),
        "HOST_MODELS_DIR_SH": shell_quote(project["host_models_dir"]),
        "CONTAINER_MODELS_DIR_SH": shell_quote(CONTAINER_MODELS_DIR),
        "HOOK_MODULE_SH": shell_quote(hook_module),
        "GENERATED_AT": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }

    is_sglang_pd = project["framework"] == "sglang" and (
        project["deployment"] == "pd" or project["deployment"].startswith("pd-")
    )
    template_name = "inference-project-pd" if is_sglang_pd else "inference-project"
    template_root = Path(__file__).resolve().parent / "templates" / template_name
    if not template_root.is_dir():
        fail(f"template directory not found: {template_root}")
    if args.dry_run:
        print(target)
        return 0

    shared = Path(__file__).resolve().parent / "templates" / "shared"
    stable_files = {
        shared / "client" / "analyze_torch_trace.py": target / "client" / "analyze_torch_trace.py",
        shared / "client" / "time_profile.py": target / "client" / "time_profile.py",
        shared / "client" / "run_time_profile.py": target / "client" / "run_time_profile.py",
        shared / "client" / "validate_time_window.py": target / "client" / "validate_time_window.py",
    }
    missing_sources = [str(source) for source in stable_files if not source.is_file()]
    if missing_sources:
        fail("shared template file(s) not found: " + ", ".join(missing_sources))

    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(template_root.rglob("*")):
        relative = source.relative_to(template_root)
        if relative.parts[0] == "tuning":
            continue  # Optimization artifacts are created only for an authorized study.
        if "__pycache__" in relative.parts or source.suffix in (".pyc", ".pyo"):
            continue
        rendered_parts = [part.replace("__TITLE__", title).replace("__HOOK_MODULE__", hook_module) for part in relative.parts]
        destination = target.joinpath(*rendered_parts)
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if destination.exists():
            # Preserve the user's design table and any pre-generation evidence log.
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        destination.write_text(render_text(text, tokens, source), encoding="utf-8", newline="\n")

    for source, destination in stable_files.items():
        shutil.copyfile(source, destination)

    if os.name != "nt":
        for script in target.rglob("*.sh"):
            script.chmod(script.stat().st_mode | 0o111)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
