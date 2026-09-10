"""The executable completion contract.

"Done" is not a claim an agent gets to make in prose. It is a list of commands
that either exit as expected or do not. Criteria are declared in
``spec/05-gate.md`` as ```` ```gatekit-criterion ```` JSON fences, frozen into
``.gatekit/contract.json`` by :func:`derive`, and executed by :func:`execute`.

Three rules keep the result honest:

* **Timeouts are ``unverified``, never ``ok`` and never ``fail``.** A command
  that ran out of time told us nothing about the code.
* **Artifacts must stay inside the project root**, checked after
  ``os.path.realpath`` so a symlink cannot point the evidence somewhere else.
* **A stale contract short-circuits to ``unverified``.** If ``05-gate.md``
  changed after derivation, the frozen criteria no longer describe the
  agreed-upon gate, so running them would answer the wrong question.

Commands run through ``subprocess.run`` with no shell: ``argv`` is a list and
stays a list, so a criterion cannot smuggle in shell metacharacters.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from . import approval, config, paths, verdict

VERSION = 1

#: Total wall-clock budget for a whole contract run (ARCHITECTURE.md section 5).
TOTAL_BUDGET_S = 45.0

#: Per-criterion default when the fence omits ``timeout_s``.
DEFAULT_TIMEOUT_S = 30

#: How much of stdout/stderr is retained per criterion.
TAIL_CHARS = 2000

FENCE_NAME = "gatekit-criterion"

STALE_REASON = "contract_stale"

# Matches a fenced block whose info string is exactly the fence name. The
# opening fence must start at the beginning of a line, which keeps prose that
# merely mentions the fence name out of the results.
_FENCE_RE = re.compile(
    r"^[ \t]*```[ \t]*(?P<name>[A-Za-z0-9_-]+)[ \t]*\r?\n(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def parse_fences(text: str, name: str) -> List[Dict[str, Any]]:
    """Return the JSON objects of every ```` ```<name> ```` fence in *text*.

    Raises :class:`ValueError` naming the fence index when a block does not
    parse, so the user learns which one to fix rather than getting a bare
    "invalid JSON".
    """
    results: List[Dict[str, Any]] = []
    index = 0
    for match in _FENCE_RE.finditer(text or ""):
        if match.group("name") != name:
            continue
        index += 1
        body = match.group("body")
        try:
            parsed = json.loads(body)
        except ValueError as err:
            raise ValueError(f"{name} fence #{index} is not valid JSON: {err}") from err
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} fence #{index} must contain a JSON object")
        results.append(parsed)
    return results


def _normalize_criterion(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Validate one criterion and fill in its defaults."""
    ident = raw.get("id")
    if not isinstance(ident, str) or not ident.strip():
        raise ValueError(f"criterion #{index} is missing a non-empty string 'id'")

    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError(f"criterion '{ident}' needs 'argv' as a non-empty list of strings")

    expect = raw.get("expect")
    if not isinstance(expect, dict):
        expect = {"exit": 0}
    expect.setdefault("exit", 0)

    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []

    try:
        timeout_s = float(raw.get("timeout_s", DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout_s = float(DEFAULT_TIMEOUT_S)
    if timeout_s <= 0:
        timeout_s = float(DEFAULT_TIMEOUT_S)

    return {
        "id": ident.strip(),
        "argv": list(argv),
        "expect": expect,
        "timeout_s": timeout_s,
        "artifacts": [str(a) for a in artifacts],
    }


def gate_file(root: pathlib.Path) -> pathlib.Path:
    return paths.spec_dir(root) / "05-gate.md"


def derive(root: pathlib.Path) -> Dict[str, Any]:
    """Parse ``spec/05-gate.md`` into ``.gatekit/contract.json`` and return it."""
    source = gate_file(root)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as err:
        raise FileNotFoundError(f"cannot read {source}: {err}") from err

    raw_criteria = parse_fences(text, FENCE_NAME)
    criteria = [_normalize_criterion(item, i + 1) for i, item in enumerate(raw_criteria)]

    seen = set()
    for crit in criteria:
        if crit["id"] in seen:
            raise ValueError(f"duplicate criterion id '{crit['id']}'")
        seen.add(crit["id"])

    data = {
        "version": VERSION,
        "source_sha256": approval.sha256_file(source),
        "criteria": criteria,
        "derived_at": _now(),
    }
    config.write_json_atomic(paths.contract_file(root), data)
    return data


def load(root: pathlib.Path) -> Optional[Dict[str, Any]]:
    """Read ``.gatekit/contract.json``, or ``None`` when absent/corrupt."""
    try:
        raw = json.loads(paths.contract_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def status(root: pathlib.Path) -> str:
    """``ok`` when fresh, ``fail`` when stale, ``unverified`` when absent."""
    data = load(root)
    if data is None:
        return verdict.UNVERIFIED
    current = approval.sha256_file(gate_file(root))
    if not current:
        return verdict.FAIL
    return verdict.OK if current == data.get("source_sha256") else verdict.FAIL


def _tail(text: str) -> str:
    """Keep the last :data:`TAIL_CHARS` characters — errors live at the end."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= TAIL_CHARS:
        return text
    return "…(truncated)…" + text[-TAIL_CHARS:]


def _artifact_hashes(
    root: pathlib.Path, artifacts: List[str]
) -> "tuple[Dict[str, str], List[str]]":
    """Hash each artifact, reporting any that is missing or escapes the root.

    Containment is checked on the realpath so a symlink pointing outside the
    project cannot be presented as evidence produced inside it.
    """
    hashes: Dict[str, str] = {}
    problems: List[str] = []
    real_root = os.path.realpath(str(root))

    for entry in artifacts:
        rel = str(entry)
        if os.path.isabs(rel):
            problems.append(f"artifact must be relative: {rel}")
            continue
        if ".." in pathlib.PurePosixPath(rel.replace("\\", "/")).parts:
            problems.append(f"artifact must not contain '..': {rel}")
            continue

        candidate = pathlib.Path(root) / rel
        real = os.path.realpath(str(candidate))
        if real != real_root and not real.startswith(real_root + os.sep):
            problems.append(f"artifact escapes the project root: {rel}")
            continue
        if not os.path.isfile(real):
            problems.append(f"missing artifact: {rel}")
            continue

        digest = approval.sha256_file(pathlib.Path(real))
        if not digest:
            problems.append(f"unreadable artifact: {rel}")
            continue
        hashes[rel] = digest

    return hashes, problems


def _run_one(
    root: pathlib.Path, crit: Dict[str, Any], remaining: float
) -> Dict[str, Any]:
    """Execute one criterion and classify the outcome."""
    result: Dict[str, Any] = {
        "id": crit["id"],
        "verdict": verdict.UNVERIFIED,
        "exit": None,
        "elapsed_s": 0.0,
        "stdout_tail": "",
        "stderr_tail": "",
        "artifact_hashes": {},
    }

    if remaining <= 0:
        result["stderr_tail"] = "budget exhausted before this criterion ran"
        return result

    timeout = min(float(crit.get("timeout_s", DEFAULT_TIMEOUT_S)), remaining)
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell=False by default
            list(crit["argv"]),
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        result["stderr_tail"] = f"timeout after {timeout:.1f}s"
        return result  # stays unverified
    except (OSError, ValueError) as err:
        # Missing binary, permission denied, bad argv: we learned nothing about
        # the code under test, so this is unverified rather than a failure.
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        result["stderr_tail"] = f"could not execute: {err}"
        return result

    result["elapsed_s"] = round(time.monotonic() - started, 3)
    result["exit"] = completed.returncode
    result["stdout_tail"] = _tail(completed.stdout)
    result["stderr_tail"] = _tail(completed.stderr)

    expected_exit = crit.get("expect", {}).get("exit", 0)
    if completed.returncode != expected_exit:
        result["verdict"] = verdict.FAIL
        return result

    hashes, problems = _artifact_hashes(root, crit.get("artifacts", []))
    result["artifact_hashes"] = hashes
    if problems:
        result["verdict"] = verdict.FAIL
        result["stderr_tail"] = _tail(
            (result["stderr_tail"] + "\n" + "; ".join(problems)).strip()
        )
        return result

    result["verdict"] = verdict.OK
    return result


def execute(root: pathlib.Path, total_budget_s: float = TOTAL_BUDGET_S) -> Dict[str, Any]:
    """Run every criterion within *total_budget_s* and aggregate the verdict.

    Returns ``{"verdict", "criteria", "reasons"}``. ``reasons`` holds short
    human-readable strings naming what failed or went unverified; the stop gate
    puts them in front of the user.
    """
    data = load(root)
    if data is None:
        return {
            "verdict": verdict.UNVERIFIED,
            "criteria": [],
            "reasons": ["no contract: run `gatekit contract derive` first"],
        }

    if status(root) != verdict.OK:
        return {
            "verdict": verdict.UNVERIFIED,
            "criteria": [],
            "reasons": [STALE_REASON],
        }

    criteria = data.get("criteria") or []
    if not criteria:
        return {
            "verdict": verdict.UNVERIFIED,
            "criteria": [],
            "reasons": ["contract has no criteria"],
        }

    deadline = time.monotonic() + float(total_budget_s)
    results: List[Dict[str, Any]] = []
    for crit in criteria:
        results.append(_run_one(root, crit, deadline - time.monotonic()))

    reasons: List[str] = []
    for item in results:
        if item["verdict"] == verdict.FAIL:
            reasons.append(f"{item['id']}: fail (exit {item['exit']})")
        elif item["verdict"] == verdict.UNVERIFIED:
            detail = item.get("stderr_tail") or "not verified"
            reasons.append(f"{item['id']}: unverified ({detail.strip().splitlines()[0][:120]})")

    return {
        "verdict": verdict.aggregate(results),
        "criteria": results,
        "reasons": reasons,
    }


def run(argv: List[str]) -> int:
    """``gatekit contract derive|status|run [--json]``."""
    parser = argparse.ArgumentParser(prog="gatekit contract", add_help=True)
    parser.add_argument("action", choices=["derive", "status", "run"])
    parser.add_argument("--root", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--budget", type=float, default=TOTAL_BUDGET_S)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    root = paths.project_root(args.root)

    if args.action == "derive":
        try:
            data = derive(root)
        except (FileNotFoundError, ValueError) as err:
            print(f"gatekit: {err}", file=sys.stderr)
            return 1
        if args.as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"derived {len(data['criteria'])} criteria -> {paths.contract_file(root)}")
        return 0

    if args.action == "status":
        print(status(root))
        return 0 if status(root) == verdict.OK else 1

    result = execute(root, total_budget_s=args.budget)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["verdict"])
        for reason in result["reasons"]:
            print(f"  - {reason}")
    return 0 if result["verdict"] == verdict.OK else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
