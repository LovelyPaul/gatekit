"""``gatekit migrate`` — move a project's state directory to another name.

ADR-0029. Dry run by default; ``--apply`` renames ``.<old>/`` to ``.<to>/``
(``git mv`` when anything under it is tracked), rewrites the ``.gitignore``
lines that name the old directory, and regenerates the Codex layer when one
is present. It never reads or writes ``spec/``, does nothing when the
directory already has the target name, and refuses when both exist.
``--to`` defaults to the current name, so before the rename it is a no-op;
``--to gatebound`` rehearses it.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List

from gatekit import config, names, paths


def _tracked(root: pathlib.Path, rel: str) -> bool:
    """True when git tracks anything under *rel* in *root*'s repository."""
    if shutil.which("git") is None:
        return False
    try:
        proc = subprocess.run(["git", "ls-files", "--", rel], cwd=str(root),
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _gitignore_rewrite(text: str, old: str, new: str) -> str:
    """*text* with every ``.gitignore`` path naming directory *old* renamed."""
    pattern = re.compile(r"(?<![A-Za-z0-9_.-])%s(?=/|$|\s)" % re.escape(old))
    out = []
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("#"):
            out.append(line)
        else:
            out.append(pattern.sub(new, line))
    return "".join(out)


def _has_agents_block(root: pathlib.Path) -> bool:
    agents = root / "AGENTS.md"
    try:
        text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    except OSError:
        return False
    return any(names.agents_markers(n)[0] in text for n in names.all_names())


def plan(root: pathlib.Path, to: str) -> Dict[str, Any]:
    """What ``--apply`` would do: ``{"from", "to", "actions", "refused", "detail"}``."""
    root = pathlib.Path(root)
    target = "." + to
    found = names.existing_state_dirs(root)
    report: Dict[str, Any] = {"root": str(root), "from": None, "to": target,
                              "actions": [], "refused": False, "detail": ""}
    if len(found) > 1:
        report["refused"] = True
        report["detail"] = ("both %s exist; keep one (doctor says which the hooks use) "
                            "and delete the other first" % " and ".join(p.name for p in found))
        return report
    if not found:
        report["detail"] = "no state directory; nothing to migrate"
        return report
    source = found[0].name
    report["from"] = source
    if source == target:
        report["detail"] = "already %s/; nothing to do" % target
        return report
    if (root / target).exists():
        report["refused"] = True
        report["detail"] = "%s exists and is not a directory" % target
        return report
    actions: List[Dict[str, str]] = []
    how = "git mv" if _tracked(root, source) else "rename"
    actions.append({"action": how, "from": source, "to": target})
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        if _gitignore_rewrite(text, source, target) != text:
            actions.append({"action": "rewrite", "path": ".gitignore"})
    if (root / ".codex" / "hooks.json").is_file():
        actions.append({"action": "regenerate", "path": ".codex/, .agents/skills/, AGENTS.md"})
    elif _has_agents_block(root):
        actions.append({"action": "regenerate", "path": "AGENTS.md"})
    report["actions"] = actions
    report["detail"] = "%s/ -> %s/" % (source, target)
    return report


def apply(root: pathlib.Path, report: Dict[str, Any]) -> None:
    """Carry out *report*'s actions. Raises ``OSError``/``ValueError`` on failure."""
    root = pathlib.Path(root)
    for step in report["actions"]:
        kind = step["action"]
        if kind == "git mv":
            proc = subprocess.run(["git", "mv", step["from"], step["to"]], cwd=str(root),
                                  capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                raise OSError("git mv failed: %s" % proc.stderr.strip()[:200])
            # `git mv` moves only what git tracks; carry the rest (runs/, jobs/).
            leftover = root / step["from"]
            if leftover.exists():
                _merge_into(leftover, root / step["to"])
        elif kind == "rename":
            (root / step["from"]).rename(root / step["to"])
        elif kind == "rewrite":
            path = root / step["path"]
            text = path.read_text(encoding="utf-8")
            config.write_text_atomic(path, _gitignore_rewrite(text, report["from"], report["to"]))
        elif kind == "regenerate":
            from gatekit import hosts
            if step["path"] == "AGENTS.md":
                agents = root / "AGENTS.md"
                config.write_text_atomic(agents, hosts.merged_agents_md(
                    agents.read_text(encoding="utf-8"), paths.plugin_root()))
            else:
                hosts.install(root, "codex")


def _merge_into(source: pathlib.Path, dest: pathlib.Path) -> None:
    """Move every entry of *source* into *dest* (recursively), then remove it."""
    dest.mkdir(parents=True, exist_ok=True)
    for entry in list(source.iterdir()):
        target = dest / entry.name
        if entry.is_dir() and target.is_dir():
            _merge_into(entry, target)
        elif not target.exists():
            entry.rename(target)
    try:
        source.rmdir()
    except OSError:
        pass


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="gatekit migrate", add_help=True)
    parser.add_argument("--root", default=None, help="project root (default: detected)")
    parser.add_argument("--to", default=names.CURRENT, choices=list(names.all_names()),
                        help="target name (default: %s)" % names.CURRENT)
    parser.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    root = pathlib.Path(args.root).expanduser() if args.root else paths.project_root()
    report = plan(root, args.to)
    report["applied"] = False
    code = 1 if report["refused"] else 0
    if args.apply and not report["refused"] and report["actions"]:
        try:
            apply(root, report)
            report["applied"] = True
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            report["detail"] = "failed: %s" % exc
            code = 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        verb = "migrated" if report["applied"] else ("refused" if report["refused"] else
                                                     ("would do" if report["actions"] else "ok"))
        print("%s: %s" % (verb, report["detail"]))
        for step in report["actions"]:
            print("  " + " ".join("%s=%s" % kv for kv in step.items()))
        if report["actions"] and not args.apply:
            print("dry run; pass --apply to make these changes (spec/ is never touched)")
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
