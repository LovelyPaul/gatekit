"""Tests for gatekit.lang — output language detection (ko/en)."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import lang

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1]


class TestDetect(unittest.TestCase):
    def test_empty_is_en(self) -> None:
        self.assertEqual(lang.detect(""), "en")

    def test_none_is_en(self) -> None:
        self.assertEqual(lang.detect(None), "en")  # type: ignore[arg-type]

    def test_pure_english_is_en(self) -> None:
        self.assertEqual(lang.detect("Please build the login screen"), "en")

    def test_pure_korean_is_ko(self) -> None:
        self.assertEqual(lang.detect("로그인 화면을 만들어줘"), "ko")

    def test_jamo_counts_as_hangul(self) -> None:
        self.assertEqual(lang.detect("ㅇㅇ ㄱㄱ"), "ko")

    def test_no_letters_at_all_is_en(self) -> None:
        self.assertEqual(lang.detect("123 !!! ---"), "en")
        self.assertEqual(lang.detect("   "), "en")

    def test_mixed_above_threshold_is_ko(self) -> None:
        # 6 Hangul letters, 4 Latin letters -> 60% >= 30%
        self.assertEqual(lang.detect("로그인화면 auth"), "ko")

    def test_mixed_below_threshold_is_en(self) -> None:
        # 2 Hangul vs 40 Latin letters -> ~4.8% < 30%
        text = "Implement the authentication middleware carefully 로그"
        self.assertEqual(lang.detect(text), "en")

    def test_threshold_is_thirty_percent_inclusive(self) -> None:
        # exactly 3 Hangul out of 10 letters == 30% -> ko
        self.assertEqual(lang.detect("가나다abcdefg"), "ko")
        # 2 out of 10 == 20% -> en
        self.assertEqual(lang.detect("가나abcdefgh"), "en")

    def test_punctuation_and_digits_are_not_counted(self) -> None:
        # Digits and separators must not dilute the ratio: 3 Hangul letters vs
        # 3 Latin letters is 50% even though most characters are ASCII.
        self.assertEqual(lang.detect("v1.2.3 / 100% -- 고쳐줘 now"), "ko")

    def test_path_tokens_do_not_count(self) -> None:
        # Observed in a Codex session: "src/hello.ts 만들어줘" flipped the
        # session to English. Paths and identifiers are named, not written.
        self.assertEqual(lang.detect("src/auth/token.ts 를 고쳐줘"), "ko")
        self.assertEqual(lang.detect("src/hello.ts 만들어줘"), "ko")
        self.assertEqual(lang.detect("README.md 읽어줘"), "ko")
        self.assertEqual(lang.detect("`user_id` 컬럼 추가"), "ko")

    def test_english_around_a_path_stays_english(self) -> None:
        self.assertEqual(lang.detect("please create src/hello.ts now"), "en")
        self.assertEqual(lang.detect("make src/hello.ts"), "en")

    def test_trailing_period_is_not_an_identifier_marker(self) -> None:
        self.assertEqual(lang.detect("Hello world."), "en")
        self.assertEqual(lang.detect("안녕하세요 world."), "ko")

    def test_only_identifiers_is_english(self) -> None:
        self.assertEqual(lang.detect("src/a.ts src/b.ts"), "en")

    def test_cjk_han_is_not_hangul(self) -> None:
        self.assertEqual(lang.detect("漢字 only here"), "en")


class TestFromSpec(unittest.TestCase):
    """ADR-0026: the spec's language, for a session whose prompts said nothing."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / "spec").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> None:
        (self.root / "spec" / name).write_text(text, encoding="utf-8")

    def test_no_spec_is_none(self) -> None:
        self.assertIsNone(lang.from_spec(self.root))

    def test_korean_prd(self) -> None:
        self.write("01-prd.md", "# 메모 앱\n\n## 문제\n사용자는 메모를 빠르게 남기고 싶다.\n")
        self.assertEqual(lang.from_spec(self.root), "ko")

    def test_english_prd(self) -> None:
        self.write("01-prd.md", "# Notes app\n\n## Problem\nUsers want to jot notes fast.\n")
        self.assertEqual(lang.from_spec(self.root), "en")

    def test_discovery_when_no_prd(self) -> None:
        self.write("00-discovery.md", "# 발견\n\n사용자 인터뷰 기록\n")
        self.assertEqual(lang.from_spec(self.root), "ko")

    def test_prd_wins_over_discovery(self) -> None:
        self.write("00-discovery.md", "# 발견\n\n사용자 인터뷰 기록\n")
        self.write("01-prd.md", "# Notes app\n\nUsers want to jot notes fast.\n")
        self.assertEqual(lang.from_spec(self.root), "en")

    def test_only_the_head_is_read(self) -> None:
        body = "# Notes app\n" + "Plain English line.\n" * 45 + "한국어 " * 500 + "\n"
        self.write("01-prd.md", body)
        self.assertEqual(lang.from_spec(self.root), "en")

    def test_korean_prd_with_english_tables_and_code(self) -> None:
        # Review of 0.16.1: Korean headings and prose, but the head is mostly
        # an English metric table and a TypeScript fence.
        self.write("01-prd.md", (
            '---\ntitle: "Checkout API — 제품 요구 정의"\ndate: "2026-10-01"\n'
            'status: "draft"\n---\n'
            "# Checkout API — 제품 요구 정의\n## 문제\n"
            "| Metric | Current | Source | Date |\n|---|---|---|---|\n"
            "| p95 latency of POST /orders endpoint | 1200ms | Datadog APM dashboard | 2026-09 |\n"
            "| error rate for payment webhook retries | 2.3% | Sentry issues | 2026-09 |\n"
            "| conversion rate checkout funnel step three | 41% | Amplitude funnel report | 2026-09 |\n"
            "```ts\nexport async function createOrder(request: Request, response: Response) "
            '{ return response.json({ status: "created", orderId }) }\n```\n'
            "결제 실패가 많다. `POST /orders` 응답이 느리다.\n"))
        self.assertEqual(lang.from_spec(self.root), "ko")

    def test_english_prd_with_korean_product_name(self) -> None:
        self.write("01-prd.md", (
            '---\ntitle: "모두의가계부 — Product requirements"\n---\n'
            "# 모두의가계부 — Product requirements\n## Problem\n"
            "Users of 모두의가계부 lose track of shared spending.\n"
            "| 항목 | 값 |\n|---|---|\n| 월간 사용자 | 1200 |\n"
            "## Goals\n- cut reconciliation to 60s\n"))
        self.assertEqual(lang.from_spec(self.root), "en")

    def test_head_counts_prose_lines_not_raw_lines(self) -> None:
        # A long English table at the top does not use up the head.
        table = "| Metric | Value |\n|---|---|\n" + "| p95 latency | 1200ms |\n" * 60
        self.write("01-prd.md", table + "# 결제 개선\n결제 실패를 줄인다.\n")
        self.assertEqual(lang.from_spec(self.root), "ko")

    def test_only_code_and_tables_is_none(self) -> None:
        self.write("01-prd.md", "```ts\nconst a = 1\n```\n| a | b |\n|---|---|\n")
        self.assertIsNone(lang.from_spec(self.root))

    def test_frontmatter_after_a_bom_is_skipped(self) -> None:
        # Review of 0.16.2: a BOM hid the opening `---`, so the English
        # frontmatter was read as prose.
        self.write("01-prd.md", (
            "\ufeff---\ntitle: Checkout API product requirements\n"
            "owner: platform team payments squad\nstatus: draft\n---\n"
            "# 결제 개선\n결제 실패를 줄인다.\n"))
        self.assertEqual(lang.from_spec(self.root), "ko")

    def test_unclosed_frontmatter_is_not_swallowed(self) -> None:
        # Review of 0.16.2: a leading `---` with no close hid the whole file.
        self.write("01-prd.md", "---\n# 제목\n결제 실패를 줄인다.\n")
        self.assertEqual(lang.from_spec(self.root), "ko")

    def test_frontmatter_closed_too_late_is_a_thematic_break(self) -> None:
        text = "---\n" + "결제 실패를 줄인다.\n" * 70 + "---\n"
        self.assertTrue(lang.prose_head(text.splitlines(True)).startswith("---\n결제"))

    def test_frontmatter_closed_within_the_limit_is_skipped(self) -> None:
        text = "---\n" + "key: value\n" * 58 + "---\n# 제목\n"
        self.assertEqual(lang.prose_head(text.splitlines(True)), "# 제목")
        # From a generator, as from_spec passes it.
        self.assertEqual(lang.prose_head(iter(text.splitlines(True))), "# 제목")

    def test_spec_without_letters_is_none(self) -> None:
        self.write("01-prd.md", "---\n1. 2. 3.\n")
        self.assertIsNone(lang.from_spec(self.root))


class TestRun(unittest.TestCase):
    def test_run_prints_detected_language(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lang.run(["안녕하세요"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "ko")

    def test_run_without_args_is_en(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lang.run([])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "en")

    def test_run_joins_multiple_args(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            lang.run(["hello", "world"])
        self.assertEqual(buf.getvalue().strip(), "en")


class TestModuleEntryPoint(unittest.TestCase):
    """`python3 -m gatekit lang ...` must work with cwd=plugin and no PYTHONPATH."""

    def test_python_m_gatekit_lang(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, "-m", "gatekit", "lang", "안녕하세요"],
            cwd=str(PLUGIN_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ko")

    def test_python_m_gatekit_help(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, "-m", "gatekit", "--help"],
            cwd=str(PLUGIN_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("lang", proc.stdout)



class TestRunSpec(unittest.TestCase):
    """Review of 0.16.3: commands detected the language from
    `head -40 spec/01-prd.md`, which a table-heavy Korean PRD misreads.
    `lang --spec` uses the hook's logic (`from_spec`), then the latest
    session ledger, then `en`."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        (self.root / ".gatekit").mkdir()

    def run_spec(self, *extra: str) -> str:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lang.run(["--spec", "--root", str(self.root), *extra])
        self.assertEqual(rc, 0)
        return buf.getvalue().strip()

    def write_prd(self, text: str) -> None:
        (self.root / "spec").mkdir(exist_ok=True)
        (self.root / "spec" / "01-prd.md").write_text(text, encoding="utf-8")

    def write_ledger(self, name: str, output_lang: str, mtime: float,
                     lang_source=None) -> None:
        import json

        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        path = runs / (name + ".json")
        path.write_text(json.dumps({"session_id": name, "output_lang": output_lang,
                                    "lang_source": lang_source}),
                        encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_table_heavy_korean_prd_is_ko(self) -> None:
        rows = "".join("| F-%02d | Login API endpoint `POST /api/v1/auth` | P0 | REST |\n" % i
                       for i in range(30))
        prd = ("---\ntitle: Memo board PRD\nstatus: draft\n---\n"
               "| ID | Feature | Priority | Type |\n|---|---|---|---|\n" + rows
               + "\n# 메모 보드\n\n팀이 함께 쓰는 메모 보드를 만든다. 로그인한 사용자만 메모를 쓴다.\n")
        self.write_prd(prd)
        # The old command form reads the raw head and gets it wrong.
        self.assertEqual(lang.detect("".join(prd.splitlines(True)[:40])), "en")
        self.assertEqual(self.run_spec(), "ko")

    def test_english_prd_is_en(self) -> None:
        self.write_ledger("s1", "ko", 2000)
        self.write_prd("# Memo board\n\nA shared memo board for a small team.\n")
        self.assertEqual(self.run_spec(), "en")

    def test_no_spec_falls_back_to_the_latest_ledger(self) -> None:
        self.write_ledger("old", "en", 1000)
        self.write_ledger("new", "ko", 2000)
        (self.root / ".gatekit" / "runs" / "contract-last.json").write_text(
            '{"output_lang": "en"}', encoding="utf-8")
        os.utime(self.root / ".gatekit" / "runs" / "contract-last.json", (3000, 3000))
        self.assertEqual(self.run_spec(), "ko")

    # Review of 0.16.4: the prompt hook keeps a language the user signalled
    # in a prompt over the spec; `lang --spec` must agree with it.
    def test_prompt_signalled_ledger_wins_over_an_english_spec(self) -> None:
        self.write_prd("# Memo board\n\nA shared memo board for a small team.\n")
        self.write_ledger("old", "en", 1000, lang_source="prompt")
        self.write_ledger("new", "ko", 2000, lang_source="prompt")
        self.assertEqual(self.run_spec(), "ko")

    def test_spec_sourced_ledger_does_not_override_the_spec(self) -> None:
        self.write_prd("# Memo board\n\nA shared memo board for a small team.\n")
        self.write_ledger("new", "ko", 2000, lang_source="spec")
        self.assertEqual(self.run_spec(), "en")

    def test_only_the_newest_ledger_is_consulted_for_a_prompt_signal(self) -> None:
        self.write_prd("# Memo board\n\nA shared memo board for a small team.\n")
        self.write_ledger("old", "ko", 1000, lang_source="prompt")
        self.write_ledger("new", "en", 2000)
        self.assertEqual(self.run_spec(), "en")

    def test_pre_adr_0026_ledger_is_read_as_the_hook_reads_it(self) -> None:
        import json

        # No `lang_source` key: the hook's backfill counts a Korean ledger as
        # prompt-set, so `lang --spec` must too.
        self.write_prd("# Memo board\n\nA shared memo board for a small team.\n")
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True)
        (runs / "legacy.json").write_text(
            json.dumps({"session_id": "legacy", "output_lang": "ko"}), encoding="utf-8")
        self.assertEqual(self.run_spec(), "ko")

    def test_no_spec_uses_a_spec_sourced_ledger(self) -> None:
        self.write_ledger("new", "ko", 2000, lang_source="spec")
        self.assertEqual(self.run_spec(), "ko")

    def test_no_spec_no_ledger_is_en(self) -> None:
        self.assertEqual(self.run_spec(), "en")

    def test_unreadable_ledger_is_en(self) -> None:
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True)
        (runs / "bad.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_spec(), "en")
        (runs / "bad.json").write_text('{"output_lang": "fr"}', encoding="utf-8")
        self.assertEqual(self.run_spec(), "en")

    def test_spec_flag_through_the_launcher(self) -> None:
        self.write_prd("# 메모 보드\n\n팀이 함께 쓰는 메모 보드를 만든다.\n")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_DIR / "bin" / "gatekit.py"), "lang", "--spec"],
            cwd=str(self.root), env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ko")

    def test_commands_use_the_spec_form(self) -> None:
        for path in sorted((PLUGIN_DIR / "commands").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            # A command reading the spec's language uses `lang --spec`;
            # the positional form stays for the user's own words.
            self.assertNotIn('lang "$(head', text, path.name)
            self.assertNotIn("lang \"$(cat spec/", text, path.name)

    def test_commands_prefer_the_hook_context_line(self) -> None:
        # Review of 0.16.4: the hook already injected this turn's language;
        # `lang --spec` is only the fallback when that line is absent.
        users = 0
        for path in sorted((PLUGIN_DIR / "commands").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            if "lang --spec" not in text:
                continue
            users += 1
            self.assertIn("`output_lang=`", text, path.name)
            self.assertLess(text.index("`output_lang=`"), text.index("lang --spec"),
                            path.name)
            self.assertIn("only if it is absent", text, path.name)
        self.assertGreaterEqual(users, 4)

    def test_positional_form_is_unchanged(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            lang.run(["팀이", "함께", "쓰는", "메모"])
        self.assertEqual(buf.getvalue().strip(), "ko")

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
