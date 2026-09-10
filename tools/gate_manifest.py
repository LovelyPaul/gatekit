#!/usr/bin/env python3
"""gate_manifest.py — cross-check the plugin manifests against reality.

Why: `.claude-plugin/marketplace.json` and `plugin/.claude-plugin/plugin.json`
are the two files Claude Code actually reads to install and run gatekit.
ARCHITECTURE.md §1 fixes their shape (one plugin, `./plugin` as its source)
and §3 fixes the hook registrations. If these manifests drift from the
files on disk — a hook script that was renamed, a version bump that never
reached CHANGELOG.md — the plugin looks installed but silently fails at
runtime. This gate catches that class of drift before it ships.

Checks:
  - marketplace.json: valid JSON, has "plugins" list, exactly one plugin
    entry, its "source" resolves to an existing directory.
  - plugin.json: valid JSON, has required keys (name, version, commands,
    skills, hooks), version is semver, its "commands"/"skills"/"hooks"
    paths resolve under plugin/.
  - hooks/hooks.json (auto-loaded; must NOT also be listed in plugin.json "hooks"): valid JSON, and every
    command path found inside it — after substituting ${CLAUDE_PLUGIN_ROOT}
    with the plugin directory — resolves to an existing, non-empty file.
  - plugin.json "version" == the version in the top ("## <version> — ...")
    entry of CHANGELOG.md.

Usage:
    python3 tools/gate_manifest.py [--root PATH] [--json]

Exit code: 0 if no findings, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shlex
import sys

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$")
CHANGELOG_HEADING_RE = re.compile(r"^##\s+(\S+)")
PLUGIN_ROOT_TOKEN = "${CLAUDE_PLUGIN_ROOT}"


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def _load_json(path: pathlib.Path, findings: list[dict], rel_for_errors: str) -> dict | None:
    if not path.is_file():
        findings.append({"path": rel_for_errors, "line": 1, "message": f"missing file: {path}"})
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        findings.append(
            {"path": rel_for_errors, "line": exc.lineno, "message": f"invalid JSON: {exc.msg}"}
        )
        return None


def check_marketplace(root: pathlib.Path, findings: list[dict]) -> None:
    path = root / ".claude-plugin" / "marketplace.json"
    rel = path.relative_to(root).as_posix()
    data = _load_json(path, findings, rel)
    if data is None:
        return

    plugins = data.get("plugins")
    if not isinstance(plugins, list) or len(plugins) == 0:
        findings.append({"path": rel, "line": 1, "message": "marketplace.json must have a non-empty 'plugins' list"})
        return
    if len(plugins) != 1:
        findings.append(
            {"path": rel, "line": 1, "message": f"expected exactly one plugin entry, found {len(plugins)}"}
        )

    entry = plugins[0]
    source = entry.get("source")
    if not isinstance(source, str):
        findings.append({"path": rel, "line": 1, "message": "plugin entry missing string 'source'"})
        return
    source_dir = (root / source).resolve()
    if not source_dir.is_dir():
        findings.append({"path": rel, "line": 1, "message": f"plugin source dir does not exist: {source}"})


def check_plugin_json(root: pathlib.Path, findings: list[dict]) -> dict | None:
    path = root / "plugin" / ".claude-plugin" / "plugin.json"
    rel = path.relative_to(root).as_posix()
    data = _load_json(path, findings, rel)
    if data is None:
        return None

    required_keys = ["name", "version", "commands", "skills"]
    for key in required_keys:
        if key not in data:
            findings.append({"path": rel, "line": 1, "message": f"missing required key: '{key}'"})

    version = data.get("version")
    if isinstance(version, str) and not SEMVER_RE.match(version):
        findings.append({"path": rel, "line": 1, "message": f"version '{version}' is not valid semver"})

    plugin_dir = path.parent.parent  # plugin/
    for key in ("commands", "skills"):
        rel_path = data.get(key)
        if isinstance(rel_path, str):
            resolved = (plugin_dir / rel_path).resolve()
            if not resolved.is_dir():
                findings.append(
                    {"path": rel, "line": 1, "message": f"'{key}' path does not exist: {rel_path}"}
                )

    # Claude Code loads plugin/hooks/hooks.json automatically. Listing it again
    # under plugin.json "hooks" makes the plugin fail to load ("Duplicate hooks
    # file detected"), so the key must be absent unless it names an *extra* file.
    hooks_rel = data.get("hooks")
    standard = plugin_dir / "hooks" / "hooks.json"
    if isinstance(hooks_rel, str):
        hooks_path = (plugin_dir / hooks_rel).resolve()
        if hooks_path == standard.resolve():
            findings.append({"path": rel, "line": 1,
                             "message": "'hooks' must not reference hooks/hooks.json; it is loaded automatically and a duplicate reference fails plugin load"})
        elif not hooks_path.is_file():
            findings.append({"path": rel, "line": 1, "message": f"'hooks' path does not exist: {hooks_rel}"})
        else:
            check_hooks_json(root, plugin_dir, hooks_path, findings)
    if standard.is_file():
        check_hooks_json(root, plugin_dir, standard, findings)
    else:
        findings.append({"path": rel, "line": 1, "message": "plugin/hooks/hooks.json is missing; gates would never fire"})

    return data


def _extract_command_paths(command: str) -> list[str]:
    """Pull out filesystem-looking tokens from a hook 'command' string."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    paths = []
    for tok in tokens:
        if PLUGIN_ROOT_TOKEN in tok:
            paths.append(tok)
    return paths


def check_hooks_json(
    root: pathlib.Path, plugin_dir: pathlib.Path, hooks_path: pathlib.Path, findings: list[dict]
) -> None:
    rel = hooks_path.relative_to(root).as_posix()
    data = _load_json(hooks_path, findings, rel)
    if data is None:
        return

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        findings.append({"path": rel, "line": 1, "message": "'hooks' must be an object"})
        return

    found_any = False
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                if not command:
                    continue
                for tok in _extract_command_paths(command):
                    found_any = True
                    substituted = tok.replace(PLUGIN_ROOT_TOKEN, str(plugin_dir))
                    resolved = pathlib.Path(substituted).resolve()
                    if not resolved.is_file() or resolved.stat().st_size == 0:
                        findings.append(
                            {
                                "path": rel,
                                "line": 1,
                                "message": (
                                    f"{event_name}: hook script missing or empty: {tok}"
                                ),
                            }
                        )
    if not found_any:
        findings.append({"path": rel, "line": 1, "message": "no hook command scripts found in hooks.json"})


def check_version_matches_changelog(root: pathlib.Path, plugin_version: str | None, findings: list[dict]) -> None:
    if plugin_version is None:
        return
    changelog_path = root / "CHANGELOG.md"
    rel = changelog_path.relative_to(root).as_posix()
    if not changelog_path.is_file():
        findings.append({"path": rel, "line": 1, "message": "CHANGELOG.md is missing"})
        return

    top_version = None
    for lineno, line in enumerate(changelog_path.read_text(encoding="utf-8").splitlines(), start=1):
        match = CHANGELOG_HEADING_RE.match(line)
        if match:
            top_version = match.group(1)
            top_lineno = lineno
            break

    if top_version is None:
        findings.append({"path": rel, "line": 1, "message": "no '## <version>' heading found"})
        return

    if top_version != plugin_version:
        findings.append(
            {
                "path": rel,
                "line": top_lineno,
                "message": (
                    f"top CHANGELOG entry '{top_version}' does not match "
                    f"plugin.json version '{plugin_version}'"
                ),
            }
        )


def scan(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []
    check_marketplace(root, findings)
    plugin_data = check_plugin_json(root, findings)
    plugin_version = plugin_data.get("version") if isinstance(plugin_data, dict) else None
    if isinstance(plugin_version, str):
        check_version_matches_changelog(root, plugin_version, findings)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else repo_root()
    findings = scan(root)

    if args.json:
        print(json.dumps({"verdict": "fail" if findings else "ok", "findings": findings}))
    else:
        for f in findings:
            print(f"{f['path']}:{f['line']}: {f['message']}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
