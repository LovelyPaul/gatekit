"""Spec set validation (`python3 -m gatekit spec validate`).

Validates the seven files under `spec/` against the canonical heading map and
the structural conventions the rest of gatekit depends on:

* which files exist (01-prd.md and 05-gate.md are required, rest warn;
  00-discovery.md is an optional stage whose absence is silent)
* 00-discovery.md: one ```gatekit-discovery fence; each unfilled deepening
  gate is a warn, never silent
* headings: every canonical heading present, no heading from the other
  language's set (cross-language residue is a hard fail)
* 01-prd.md: inline assumption blockquotes match the assumption ledger table
* 04-tasks.md: ```gatekit-task fences are well-formed and mutually consistent
* 05-gate.md: ```gatekit-criterion fences are well-formed, plus a
  "not counted as done" section
* traceability: every task id is referenced somewhere in 05-gate.md

Findings never round `unverified` to either side; see verdict.py.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

from gatekit import lang as lang_mod
from gatekit import paths
from gatekit import verdict as V

# --------------------------------------------------------------------------
# heading map
# --------------------------------------------------------------------------

_HEADING_MAP_CACHE: Optional[Dict[str, Any]] = None


def heading_map() -> Dict[str, Any]:
    """Load `plugin/spec-kit/heading-map.json` (cached)."""
    global _HEADING_MAP_CACHE
    if _HEADING_MAP_CACHE is None:
        path = paths.plugin_root() / "spec-kit" / "heading-map.json"
        with path.open(encoding="utf-8") as fh:
            _HEADING_MAP_CACHE = json.load(fh)
    return _HEADING_MAP_CACHE


def spec_files() -> List[str]:
    return list(heading_map()["files"])


def required_files() -> List[str]:
    return list(heading_map()["required_files"])


def absent_ok_files() -> List[str]:
    """Optional stages: a missing file is not a finding."""
    return list(heading_map().get("absent_ok", []))


# --------------------------------------------------------------------------
# fence parsing
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<ticks>`{3,})[ \t]*(?P<name>[A-Za-z0-9_-]+)[ \t]*$"
)


def _iter_fences(text: str, name: str):
    """Yield (start_line_number, body_text) for each ```<name> fence.

    Line numbers are 1-based and point at the opening fence line, so error
    messages can name the exact place a malformed block starts.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = _FENCE_RE.match(lines[i])
        if not match or match.group("name") != name:
            i += 1
            continue
        ticks = match.group("ticks")
        closing = re.compile(r"^[ \t]*" + "`" * len(ticks) + r"[ \t]*$")
        body: List[str] = []
        j = i + 1
        while j < len(lines) and not closing.match(lines[j]):
            body.append(lines[j])
            j += 1
        yield i + 1, "\n".join(body)
        i = j + 1


def parse_fences(text: str, name: str) -> List[dict]:
    """Return the decoded JSON object of every ```<name> fence in `text`.

    Malformed blocks are skipped here and reported by the validators, which
    use `_parse_fences_detailed` to keep the line number.
    """
    return [item for _, item, err in _parse_fences_detailed(text, name) if err is None]


def _parse_fences_detailed(text: str, name: str):
    """Yield (line_no, parsed_or_None, error_message_or_None)."""
    out = []
    for line_no, body in _iter_fences(text, name):
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            out.append((line_no, None, str(exc)))
            continue
        if not isinstance(parsed, dict):
            out.append((line_no, None, "fence body must be a JSON object"))
            continue
        out.append((line_no, parsed, None))
    return out


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------


def _finding(file: str, verdict: str, message: str) -> dict:
    return {"file": file, "verdict": verdict, "message": message}


# --------------------------------------------------------------------------
# messages (localized; identifiers stay untranslated)
# --------------------------------------------------------------------------

MESSAGES = {
    "ko": {
        "missing_required": "필수 파일이 없습니다.",
        "missing_optional": "파일이 없습니다. 파이프라인이 아직 이 단계를 만들지 않았을 수 있습니다.",
        "unreadable": "파일을 읽을 수 없습니다: {err}",
        "heading_missing": "필수 제목이 없습니다: {heading}",
        "cross_lang": "다른 언어({other})의 제목이 섞여 있습니다: {heading}",
        "ledger_missing_section": "가정 원장 표를 찾을 수 없습니다.",
        "ledger_orphan_inline": "본문 가정 {num}번에 대응하는 원장 행이 없습니다.",
        "ledger_orphan_row": "원장 {num}번 행에 대응하는 본문 가정 표기가 없습니다.",
        "fence_malformed": "{line}번째 줄의 ```{name} 블록 JSON이 잘못되었습니다: {err}",
        "task_no_fences": "```gatekit-task 블록이 하나도 없습니다.",
        "task_missing_id": "{line}번째 줄 작업 블록에 id가 없습니다.",
        "task_duplicate_id": "작업 id가 중복됩니다: {id}",
        "task_scope_empty": "작업 {id}의 write_scope가 비어 있습니다. 글롭 목록이거나 \"read-only\"여야 합니다.",
        "task_depends_unknown": "작업 {id}의 depends_on에 존재하지 않는 id가 있습니다: {dep}",
        "task_scope_collision": "같은 라운드({round})의 작업 {a}와 {b}의 write_scope가 겹칩니다: {glob_a} ↔ {glob_b}",
        "task_no_gate": "작업 {id}에 게이트가 없습니다. 최소 1개가 필요합니다.",
        "crit_no_fences": "```gatekit-criterion 블록이 하나도 없습니다.",
        "crit_missing_id": "{line}번째 줄 기준 블록에 id가 없습니다.",
        "crit_duplicate_id": "완료 기준 id가 중복됩니다: {id}",
        "crit_argv": "완료 기준 {id}의 argv는 비어 있지 않은 문자열 리스트여야 합니다.",
        "crit_not_done_section": "\"완료로 보지 않는 조건\" 절이 없습니다.",
        "trace_missing": "작업 {id}를 참조하는 완료 기준이 없습니다.",
        "progress_stale": "PROGRESS.md 가 마지막 잡 결과({job} · {when})보다 오래되었습니다. 세션이 중간에 끊긴 흔적입니다. `jobs results` 로 확인하고 갱신하세요.",
        "disc_no_fence": "```gatekit-discovery 블록이 정확히 하나 있어야 합니다 (현재 {count}개).",
        "disc_no_problem": "problem 이 비어 있습니다. 해법이 섞이지 않은 문제 문장 한 줄이 필요합니다.",
        "disc_gate_unfilled": "심화 게이트 {gate} 가 채워지지 않았습니다 ({why}). 일부러 건너뛰었다면 unpassed 에 적으세요.",
        "disc_gate_unpassed": "심화 게이트 {gate} 는 unpassed 로 선언되었습니다. interview 는 이 항목을 사실이 아니라 가정으로 읽습니다.",
        "disc_unknown_unpassed": "unpassed 에 알 수 없는 게이트 이름이 있습니다: {name}",
        "disc_unpassed_type": "unpassed 는 게이트 이름의 리스트여야 합니다.",
        "disc_unpassed_but_filled": "심화 게이트 {gate} 가 채워져 있는데 unpassed 에도 있습니다. 둘 중 하나를 고치세요.",
        "disc_deadline": "deadline 이 비어 있습니다. 없으면 \"none\" 이라고 적으세요.",
        "disc_user": "실사용자(user) 한 명의 이름·역할",
        "disc_current_way": "current_way 는 순서가 있는 단계 2개 이상",
        "disc_frequency_per_month": "frequency_per_month 는 숫자",
        "disc_minutes_per_run": "minutes_per_run 은 숫자",
        "disc_why_chain": "why_chain 은 문자열 리스트, 증상 + 서로 다른(바꿔 말하기 제외) '왜' 3칸 이상",
        "disc_failed_attempts": "failed_attempts 는 result 가 failed|works-but-costly 인 항목 1개 이상, 또는 \"not-applicable\"",
        "ok": "검사를 통과했습니다.",
    },
    "en": {
        "missing_required": "Required file is missing.",
        "missing_optional": "File is missing. The pipeline may not have produced this stage yet.",
        "unreadable": "File could not be read: {err}",
        "heading_missing": "Required heading is missing: {heading}",
        "cross_lang": "A heading from the other language ({other}) is present: {heading}",
        "ledger_missing_section": "Assumption ledger table not found.",
        "ledger_orphan_inline": "Inline assumption {num} has no matching ledger row.",
        "ledger_orphan_row": "Ledger row {num} has no matching inline assumption marker.",
        "fence_malformed": "Malformed JSON in the ```{name} block at line {line}: {err}",
        "task_no_fences": "No ```gatekit-task blocks found.",
        "task_missing_id": "The task block at line {line} has no id.",
        "task_duplicate_id": "Duplicate task id: {id}",
        "task_scope_empty": "Task {id} has an empty write_scope. Use a list of globs or \"read-only\".",
        "task_depends_unknown": "Task {id} depends on an unknown id: {dep}",
        "task_scope_collision": "Tasks {a} and {b} in round {round} have intersecting write_scope: {glob_a} vs {glob_b}",
        "task_no_gate": "Task {id} has no gate. At least one is required.",
        "crit_no_fences": "No ```gatekit-criterion blocks found.",
        "crit_missing_id": "The criterion block at line {line} has no id.",
        "crit_duplicate_id": "Duplicate criterion id: {id}",
        "crit_argv": "Criterion {id} needs argv to be a non-empty list of strings.",
        "crit_not_done_section": "The \"not counted as done\" section is missing.",
        "trace_missing": "No completion criterion references task {id}.",
        "progress_stale": "PROGRESS.md is older than the latest job result ({job} · {when}); a session was cut short. Check `jobs results` and update it.",
        "disc_no_fence": "Exactly one ```gatekit-discovery block is required (found {count}).",
        "disc_no_problem": "problem is empty. One problem sentence with no solution in it is required.",
        "disc_gate_unfilled": "Deepening gate {gate} is not filled ({why}). If it was skipped on purpose, list it in unpassed.",
        "disc_gate_unpassed": "Deepening gate {gate} is declared unpassed. interview reads this item as an assumption, not a fact.",
        "disc_unknown_unpassed": "unpassed names an unknown gate: {name}",
        "disc_unpassed_type": "unpassed must be a list of gate names.",
        "disc_unpassed_but_filled": "Deepening gate {gate} is filled but also listed in unpassed. Fix one of the two.",
        "disc_deadline": "deadline is empty. Write \"none\" when there is none.",
        "disc_user": "user must name one real person with a role",
        "disc_current_way": "current_way needs at least two ordered steps",
        "disc_frequency_per_month": "frequency_per_month must be a number",
        "disc_minutes_per_run": "minutes_per_run must be a number",
        "disc_why_chain": "why_chain must be a list of strings: the symptom plus at least three distinct (not reworded) whys",
        "disc_failed_attempts": "failed_attempts needs one entry with result failed|works-but-costly, or \"not-applicable\"",
        "ok": "Checks passed.",
    },
}


def _msg(lang: str, key: str, **kw) -> str:
    table = MESSAGES.get(lang) or MESSAGES["en"]
    template = table.get(key) or MESSAGES["en"][key]
    return template.format(**kw)


# --------------------------------------------------------------------------
# assumption ledger
# --------------------------------------------------------------------------

# Inline markers look like:  > ⚠️ 가정: ... (A3)   /   > ⚠️ Assumption 3: ...
_INLINE_ASSUMPTION_RE = re.compile(
    r"^\s*>\s*(?:⚠️|⚠)?\s*(?:가정|Assumption)\s*"
    r"(?:[#A]?\s*(?P<num1>\d+))?\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_TRAILING_NUM_RE = re.compile(r"\(\s*[A#]?\s*(?P<num>\d+)\s*\)\s*$")
# Ledger rows look like:  | A3 | ... | ... | ... |
_LEDGER_ROW_RE = re.compile(r"^\s*\|\s*[A#]?\s*(?P<num>\d+)\s*\|")


def _inline_assumption_numbers(text: str) -> List[int]:
    nums: List[int] = []
    for line in text.splitlines():
        match = _INLINE_ASSUMPTION_RE.match(line)
        if not match:
            continue
        num = match.group("num1")
        if num is None:
            trailing = _TRAILING_NUM_RE.search(match.group("rest").strip())
            num = trailing.group("num") if trailing else None
        if num is not None:
            nums.append(int(num))
    return nums


def _ledger_section(text: str, lang: str) -> Optional[str]:
    """Return the text of the assumption-ledger section, or None."""
    headings = heading_map()[lang]["01-prd.md"]
    ledger_heading = headings[-1]  # ledger is the last canonical heading
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == ledger_heading:
            start = idx + 1
            break
    if start is None:
        return None
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return "\n".join(lines[start:end])


def _ledger_row_numbers(section: str) -> List[int]:
    nums: List[int] = []
    for line in section.splitlines():
        match = _LEDGER_ROW_RE.match(line)
        if not match:
            continue
        # skip the separator row (|---|---|) — it never matches the digit rule
        nums.append(int(match.group("num")))
    return nums


def _check_ledger(text: str, lang: str) -> List[dict]:
    findings: List[dict] = []
    section = _ledger_section(text, lang)
    if section is None:
        # the heading check already reported the missing heading
        return findings
    inline = _inline_assumption_numbers(text)
    rows = _ledger_row_numbers(section)
    inline_set, row_set = set(inline), set(rows)
    for num in sorted(inline_set - row_set):
        findings.append(
            _finding("01-prd.md", V.FAIL, _msg(lang, "ledger_orphan_inline", num=num))
        )
    for num in sorted(row_set - inline_set):
        findings.append(
            _finding("01-prd.md", V.WARN, _msg(lang, "ledger_orphan_row", num=num))
        )
    return findings


# --------------------------------------------------------------------------
# headings
# --------------------------------------------------------------------------


def _present_headings(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            out.append(re.sub(r"\s+", " ", stripped))
    return out


def _check_headings(name: str, text: str, lang: str) -> List[dict]:
    findings: List[dict] = []
    hm = heading_map()
    other = "en" if lang == "ko" else "ko"
    canonical = hm[lang].get(name, [])
    other_set = set(hm[other].get(name, []))
    present = _present_headings(text)
    present_set = set(present)

    for heading in canonical:
        if heading not in present_set:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "heading_missing", heading=heading))
            )
    # Cross-language residue: a heading that belongs to the other language's
    # canonical set for this file and is not also valid in this language.
    canonical_set = set(canonical)
    for heading in present:
        if heading in other_set and heading not in canonical_set:
            findings.append(
                _finding(
                    name,
                    V.FAIL,
                    _msg(lang, "cross_lang", other=other, heading=heading),
                )
            )
    return findings


# --------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------


def _scope_globs(task: dict) -> List[str]:
    scope = task.get("write_scope")
    if isinstance(scope, str):
        return [] if scope == "read-only" else [scope]
    if isinstance(scope, list):
        return [g for g in scope if isinstance(g, str) and g.strip()]
    return []


def _not_done_heading(lang: str) -> str:
    """Return the canonical 'not counted as done' heading for *lang* by name.

    Looked up by content rather than by position so reordering
    heading-map.json cannot silently change which section is required.
    """
    headings = heading_map()[lang]["05-gate.md"]
    for h in headings:
        low = h.lower()
        if "not counted" in low or "완료로 보지 않는" in h:
            return h
    return headings[-1]


def _globs_intersect(a: str, b: str) -> bool:
    """Delegate to the ledger's single implementation so `spec validate` and the
    spawn gate can never disagree about what collides."""
    from gatekit.ledger import globs_intersect
    return globs_intersect(a, b)


def _check_tasks(text: str, lang: str) -> List[dict]:
    name = "04-tasks.md"
    findings: List[dict] = []
    detailed = _parse_fences_detailed(text, "gatekit-task")
    for line_no, parsed, err in detailed:
        if err is not None:
            findings.append(
                _finding(
                    name,
                    V.FAIL,
                    _msg(lang, "fence_malformed", line=line_no, name="gatekit-task", err=err),
                )
            )
    tasks = [(line_no, p) for line_no, p, err in detailed if err is None]
    if not tasks:
        if not any(err for _, _, err in detailed):
            findings.append(_finding(name, V.FAIL, _msg(lang, "task_no_fences")))
        return findings

    seen: set = set()
    ids: List[str] = []
    for line_no, task in tasks:
        tid = task.get("id")
        if not isinstance(tid, str) or not tid.strip():
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "task_missing_id", line=line_no))
            )
            continue
        if tid in seen:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "task_duplicate_id", id=tid))
            )
        seen.add(tid)
        ids.append(tid)

    for _, task in tasks:
        tid = task.get("id")
        if not isinstance(tid, str):
            continue
        scope = task.get("write_scope")
        if scope != "read-only" and not _scope_globs(task):
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "task_scope_empty", id=tid))
            )
        for dep in task.get("depends_on") or []:
            if dep not in seen:
                findings.append(
                    _finding(
                        name, V.FAIL, _msg(lang, "task_depends_unknown", id=tid, dep=dep)
                    )
                )
        gates = task.get("gates")
        if not isinstance(gates, list) or not gates:
            findings.append(_finding(name, V.FAIL, _msg(lang, "task_no_gate", id=tid)))

    # same-round write_scope intersection
    by_round: Dict[Any, List[dict]] = {}
    for _, task in tasks:
        by_round.setdefault(task.get("round", 1), []).append(task)
    for round_key, group in by_round.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                for glob_a in _scope_globs(a):
                    for glob_b in _scope_globs(b):
                        if _globs_intersect(glob_a, glob_b):
                            findings.append(
                                _finding(
                                    name,
                                    V.FAIL,
                                    _msg(
                                        lang,
                                        "task_scope_collision",
                                        round=round_key,
                                        a=a.get("id"),
                                        b=b.get("id"),
                                        glob_a=glob_a,
                                        glob_b=glob_b,
                                    ),
                                )
                            )
    return findings


# --------------------------------------------------------------------------
# gate criteria
# --------------------------------------------------------------------------


def _check_criteria(text: str, lang: str) -> List[dict]:
    name = "05-gate.md"
    findings: List[dict] = []
    detailed = _parse_fences_detailed(text, "gatekit-criterion")
    for line_no, parsed, err in detailed:
        if err is not None:
            findings.append(
                _finding(
                    name,
                    V.FAIL,
                    _msg(
                        lang,
                        "fence_malformed",
                        line=line_no,
                        name="gatekit-criterion",
                        err=err,
                    ),
                )
            )
    criteria = [(line_no, p) for line_no, p, err in detailed if err is None]
    if not criteria and not any(err for _, _, err in detailed):
        findings.append(_finding(name, V.FAIL, _msg(lang, "crit_no_fences")))

    seen: set = set()
    for line_no, crit in criteria:
        cid = crit.get("id")
        if not isinstance(cid, str) or not cid.strip():
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "crit_missing_id", line=line_no))
            )
            continue
        if cid in seen:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "crit_duplicate_id", id=cid))
            )
        seen.add(cid)
        argv = crit.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(a, str) and a != "" for a in argv)
        ):
            findings.append(_finding(name, V.FAIL, _msg(lang, "crit_argv", id=cid)))

    not_done = _not_done_heading(lang)
    if not_done not in set(_present_headings(text)):
        findings.append(_finding(name, V.FAIL, _msg(lang, "crit_not_done_section")))
    return findings


# --------------------------------------------------------------------------
# traceability
# --------------------------------------------------------------------------


def _check_traceability(tasks_text: str, gate_text: str, lang: str) -> List[dict]:
    findings: List[dict] = []
    task_ids = [
        t.get("id")
        for t in parse_fences(tasks_text, "gatekit-task")
        if isinstance(t.get("id"), str)
    ]
    for tid in task_ids:
        if tid not in gate_text:
            findings.append(
                _finding("05-gate.md", V.WARN, _msg(lang, "trace_missing", id=tid))
            )
    return findings


# --------------------------------------------------------------------------
# progress freshness
# --------------------------------------------------------------------------

_TERMINAL_STATES = ("passed", "failed", "timeout", "redelegated")


def _latest_job_finish(root: pathlib.Path):
    """``(job_id, iso)`` of the most recent terminal task status, or ``None``."""
    jobs_dir = paths.state_dir(root) / "jobs"
    if not jobs_dir.is_dir():
        return None
    latest = None
    for status_path in jobs_dir.glob("*/tasks/*/status.json"):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("state") not in _TERMINAL_STATES:
            continue
        stamp = data.get("finished_at") or data.get("updated_at")
        if not isinstance(stamp, str):
            continue
        job_id = status_path.parents[2].name
        if latest is None or stamp > latest[1]:
            latest = (job_id, stamp)
    return latest


def _iso_to_epoch(stamp: str) -> Optional[float]:
    import datetime as _dt

    text = stamp.strip().replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


def _check_progress_freshness(root: pathlib.Path, lang: str) -> List[dict]:
    """A PROGRESS.md written before the latest job finished is stale: the
    session that ran the job ended before Step 5 could record the result."""
    progress = paths.spec_dir(root) / "PROGRESS.md"
    if not progress.is_file():
        return []
    latest = _latest_job_finish(root)
    if latest is None:
        return []
    finished = _iso_to_epoch(latest[1])
    if finished is None:
        return []
    try:
        mtime = progress.stat().st_mtime
    except OSError:
        return []
    if mtime + 1.0 >= finished:
        return []
    return [_finding("PROGRESS.md", V.WARN, _msg(lang, "progress_stale", job=latest[0], when=latest[1]))]


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

#: The deepening gates, in the order the command fills them. Each unfilled
#: gate is a ``warn`` so the record stays honest about what it lacks.
DISCOVERY_GATES = (
    "user",
    "current_way",
    "frequency_per_month",
    "minutes_per_run",
    "why_chain",
    "failed_attempts",
)

_ATTEMPT_RESULTS = ("failed", "works-but-costly")

#: Two why-links whose word sets overlap this much are the same statement
#: reworded. A word-overlap test is a heuristic, not understanding: it catches
#: "files hard to find" / "hard to find files", not a true synonym. It is the
#: honest limit of a stdlib validator, and the command still requires the
#: user to confirm the cause in their own words.
_RESTATEMENT_OVERLAP = 0.6

_STOPWORDS = frozenset(
    "a an the is are was were be been it its of to in on at for and or but "
    "that this these those there they them we you i my our your not no so "
    "because since when then than very just".split()
)


def _word_set(text: str) -> set:
    words = re.findall(r"[0-9A-Za-z가-힣]+", str(text).lower())
    return {w for w in words if w not in _STOPWORDS}


def _overlap(a: set, b: set) -> float:
    """Jaccard overlap of two word sets; 0 when either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def _is_not_applicable(value: Any) -> bool:
    """``"not-applicable"`` as a bare string or as the only list item."""
    if isinstance(value, str):
        return value.strip().lower() == "not-applicable"
    return (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], str)
        and value[0].strip().lower() == "not-applicable"
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _gate_filled(gate: str, record: dict) -> bool:
    value = record.get(gate)
    if gate == "user":
        return isinstance(value, str) and bool(value.strip())
    if gate == "current_way":
        return isinstance(value, list) and len([s for s in value if isinstance(s, str) and s.strip()]) >= 2
    if gate in ("frequency_per_month", "minutes_per_run"):
        return _is_number(value) and value > 0
    if gate == "why_chain":
        if not isinstance(value, list) or len(value) < 4:
            return False
        if not all(isinstance(item, str) and item.strip() for item in value):
            return False
        accepted: List[set] = [_word_set(value[0])]
        distinct = 0
        for item in value[1:]:
            words = _word_set(item)
            if not words:
                continue
            # A link that mostly restates an earlier one is not a new "why".
            if any(_overlap(words, earlier) >= _RESTATEMENT_OVERLAP for earlier in accepted):
                continue
            accepted.append(words)
            distinct += 1
        return distinct >= 3
    if gate == "failed_attempts":
        if _is_not_applicable(value):
            return True
        if not isinstance(value, list) or not value:
            return False
        return all(
            isinstance(a, dict)
            and isinstance(a.get("tried"), str) and a["tried"].strip()
            and a.get("result") in _ATTEMPT_RESULTS
            for a in value
        )
    return False


def _check_discovery(text: str, lang: str) -> List[dict]:
    name = "00-discovery.md"
    findings: List[dict] = []
    detailed = _parse_fences_detailed(text, "gatekit-discovery")
    for line_no, _, err in detailed:
        if err is not None:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "fence_malformed", line=line_no, name="gatekit-discovery", err=err))
            )
    records = [parsed for _, parsed, err in detailed if err is None]
    if len(records) != 1:
        if not findings:  # a malformed fence was already reported above
            findings.append(_finding(name, V.FAIL, _msg(lang, "disc_no_fence", count=len(records))))
        return findings
    record = records[0]

    problem = record.get("problem")
    if not (isinstance(problem, str) and problem.strip()):
        findings.append(_finding(name, V.FAIL, _msg(lang, "disc_no_problem")))

    deadline = record.get("deadline")
    if not (isinstance(deadline, str) and deadline.strip()):
        findings.append(_finding(name, V.WARN, _msg(lang, "disc_deadline")))

    unpassed = record.get("unpassed")
    if unpassed is None:
        unpassed = []
    if not isinstance(unpassed, list):
        findings.append(_finding(name, V.FAIL, _msg(lang, "disc_unpassed_type")))
        unpassed = []
    for item in unpassed:
        if item not in DISCOVERY_GATES:
            findings.append(_finding(name, V.FAIL, _msg(lang, "disc_unknown_unpassed", name=item)))

    for gate in DISCOVERY_GATES:
        if _gate_filled(gate, record):
            if gate in unpassed:
                findings.append(_finding(name, V.WARN, _msg(lang, "disc_unpassed_but_filled", gate=gate)))
            continue
        if gate in unpassed:
            findings.append(_finding(name, V.WARN, _msg(lang, "disc_gate_unpassed", gate=gate)))
        else:
            findings.append(
                _finding(name, V.WARN, _msg(lang, "disc_gate_unfilled", gate=gate, why=_msg(lang, "disc_" + gate)))
            )
    return findings


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def validate(root: pathlib.Path, lang: Optional[str] = None) -> dict:
    """Validate the spec set under `root/spec` and return a verdict report."""
    root = pathlib.Path(root)
    sdir = paths.spec_dir(root)
    contents: Dict[str, Optional[str]] = {}
    read_errors: Dict[str, str] = {}
    for name in spec_files():
        path = sdir / name
        if not path.exists():
            contents[name] = None
            continue
        try:
            contents[name] = path.read_text(encoding="utf-8")
        except OSError as exc:
            contents[name] = None
            read_errors[name] = str(exc)

    if lang is None:
        prd = contents.get("01-prd.md")
        lang = lang_mod.detect(prd) if prd else "en"
    if lang not in heading_map():
        lang = "en"

    findings: List[dict] = []
    required = set(required_files())
    silent = set(absent_ok_files())
    for name in spec_files():
        if name in read_errors:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "unreadable", err=read_errors[name]))
            )
            continue
        if contents[name] is None:
            if name in silent:
                continue
            key = "missing_required" if name in required else "missing_optional"
            level = V.FAIL if name in required else V.WARN
            findings.append(_finding(name, level, _msg(lang, key)))

    for name in spec_files():
        text = contents.get(name)
        if text is None:
            continue
        findings.extend(_check_headings(name, text, lang))

    discovery = contents.get("00-discovery.md")
    if discovery is not None:
        findings.extend(_check_discovery(discovery, lang))

    findings.extend(_check_progress_freshness(root, lang))

    prd = contents.get("01-prd.md")
    if prd is not None:
        findings.extend(_check_ledger(prd, lang))

    tasks_text = contents.get("04-tasks.md")
    if tasks_text is not None:
        findings.extend(_check_tasks(tasks_text, lang))

    gate_text = contents.get("05-gate.md")
    if gate_text is not None:
        findings.extend(_check_criteria(gate_text, lang))

    if tasks_text is not None and gate_text is not None:
        findings.extend(_check_traceability(tasks_text, gate_text, lang))

    overall = V.aggregate([f["verdict"] for f in findings]) if findings else V.OK
    return {"verdict": overall, "findings": findings, "lang": lang}


def _render(report: dict) -> str:
    lang = report["lang"]
    lines = ["spec: " + V.render(report["verdict"], lang)]
    for finding in report["findings"]:
        lines.append(
            "  [{v}] {file}: {msg}".format(
                v=finding["verdict"], file=finding["file"], msg=finding["message"]
            )
        )
    if not report["findings"]:
        lines.append("  " + _msg(lang, "ok"))
    return "\n".join(lines)


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="gatekit spec", add_help=True)
    sub = parser.add_subparsers(dest="cmd")
    p_validate = sub.add_parser("validate", help="Validate the spec set.")
    p_validate.add_argument("--json", action="store_true", help="Emit JSON.")
    p_validate.add_argument("--root", default=None, help="Project root.")
    p_validate.add_argument("--lang", default=None, choices=["ko", "en"])
    args = parser.parse_args(argv)

    if args.cmd != "validate":
        parser.print_help()
        return 2

    # An explicit --root names the project root directly; only discover a root
    # by walking up when the caller did not say which one they meant.
    root = pathlib.Path(args.root).expanduser() if args.root else paths.project_root()
    report = validate(root, args.lang)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render(report))
    return 1 if report["verdict"] == V.FAIL else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
