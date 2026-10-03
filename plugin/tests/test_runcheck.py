"""Tests for gatekit.runcheck (ADR-0022): "ran no tests" signatures, missing
paths named by a failing command, and which task's write scope covers them."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import paths, runcheck


class plugin_with_signatures:
    """Context manager: a throwaway plugin root (found through
    CLAUDE_PLUGIN_ROOT, as an installed hook finds it) whose signature file
    holds *body*."""

    def __init__(self, body: str) -> None:
        self.body = body

    def __enter__(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        root = os.path.join(self._tmp.name, "plugin")
        os.makedirs(os.path.join(root, ".claude-plugin"))
        os.makedirs(os.path.join(root, "spec-kit"))
        with open(os.path.join(root, ".claude-plugin", "plugin.json"), "w") as h:
            h.write('{"name": "gatekit", "version": "0"}')
        with open(os.path.join(root, "spec-kit", runcheck.SIGNATURES_FILE), "w") as h:
            h.write(self.body)
        self._old = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = root
        runcheck._signatures.cache_clear()
        return root

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        else:
            os.environ["CLAUDE_PLUGIN_ROOT"] = self._old
        runcheck._signatures.cache_clear()
        self._tmp.cleanup()
        return False

#: (signature id, zero-test output, its exit code, real-run output with a
#: positive count, its exit code). Each zero-test output must be named by
#: its signature; each real run must not be named at all.
SIGNATURE_CASES = (
    ("pytest", "============ no tests ran in 0.01s ============\n", 5,
     "collected 3 items\n\ntests/test_a.py ...\n============ 3 passed in 0.12s ============\n", 0),
    ("unittest", "\n----------------------------------------------------------------------\n"
                 "Ran 0 tests in 0.000s\n\nNO TESTS RAN\n", 5,
     "....\n----------------------------------------------------------------------\n"
     "Ran 4 tests in 0.010s\n\nOK\n", 0),
    ("jest", "No tests found, exiting with code 0\n", 0,
     "PASS src/a.test.ts\nTests:       2 passed, 2 total\n", 0),
    ("vitest", "No test files found, exiting with code 0\n", 0,
     " Test Files  1 passed (1)\n      Tests  3 passed (3)\n", 0),
    ("playwright", "Error: No tests found\n", 0,
     "Running 5 tests using 2 workers\n  5 passed (3.2s)\n", 0),
    ("node-test", "# tests 0\n# suites 0\n# pass 0\n# fail 0\n", 0,
     "# tests 3\n# suites 1\n# pass 3\n# fail 0\n", 0),
    ("mocha", "\n\n  0 passing (1ms)\n\n", 0,
     "\n  thing\n    ✓ works\n\n  4 passing (12ms)\n", 0),
    ("pytest-deselected", "collected 3 items / 3 deselected / 0 selected\n"
                          "============ 3 deselected in 0.01s ============\n", 5,
     "collected 3 items / 1 deselected / 2 selected\n"
     "============ 2 passed, 1 deselected in 0.05s ============\n", 0),
    ("go", "?   \texample.com/app\t[no test files]\n", 0,
     "?   \texample.com/app/cmd\t[no test files]\nok  \texample.com/app/lib\t0.004s\n", 0),
    ("cargo", "running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored\n", 0,
     "running 5 tests\ntest a ... ok\n\ntest result: ok. 5 passed; 0 failed\n\n"
     "   Doc-tests app\n\nrunning 0 tests\n\ntest result: ok. 0 passed; 0 failed\n", 0),
)


class TestSignatureFile(unittest.TestCase):
    def test_the_data_file_lists_every_runner(self) -> None:
        path = paths.plugin_root() / "spec-kit" / "no-tests-signatures.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = {s["id"] for s in data["signatures"]}
        self.assertEqual(ids, {case[0] for case in SIGNATURE_CASES})
        for sig in data["signatures"]:
            self.assertTrue(sig.get("pattern") and sig.get("positive"), sig["id"])
            self.assertTrue(sig.get("exits"), sig["id"])

    def test_malformed_files_never_raise(self) -> None:
        cases = (
            "[]",
            '{"signatures": {"id": "x"}}',
            '{"signatures": ["not a dict", 3, null]}',
            '{"signatures": [{"id": "x", "pattern": 5, "positive": "a", "exits": [0]}]}',
            '{"signatures": [{"id": "x", "pattern": "a", "positive": "b", "exits": "0"}]}',
            '{"signatures": [{"id": "x", "pattern": "a", "positive": "b", "exits": [true]}]}',
            '{"signatures": [{"id": "x", "pattern": "a", "positive": "b", "exits": [0.5]}]}',
            "null",
        )
        for body in cases:
            with self.subTest(body=body):
                with plugin_with_signatures(body):
                    self.assertIsNone(runcheck.ran_no_tests("Ran 0 tests in 0.000s", "", 0))

    def test_one_bad_entry_does_not_disable_the_rest(self) -> None:
        body = json.dumps({"signatures": [
            {"id": "broken", "pattern": "(unclosed", "positive": "x", "exits": [0]},
            "junk",
            {"id": "bad-exits", "pattern": "a", "positive": "b", "exits": [False]},
            {"id": "unittest", "pattern": "^Ran 0 tests in\\b",
             "positive": "^Ran [1-9]\\d* tests? in\\b", "exits": [0, 5]},
        ]})
        with plugin_with_signatures(body):
            self.assertEqual(runcheck.ran_no_tests("Ran 0 tests in 0.000s", "", 0), "unittest")
            self.assertEqual([s[0] for s in runcheck._signatures()], ["unittest"])

    def test_the_digest_follows_the_file(self) -> None:
        with plugin_with_signatures('{"signatures": []}'):
            first = runcheck.signatures_digest()
        with plugin_with_signatures('{"signatures": [], "v": 2}'):
            second = runcheck.signatures_digest()
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first, second)

    def test_an_unreadable_file_means_no_signatures(self) -> None:
        runcheck._signatures.cache_clear()
        try:
            with mock.patch.object(runcheck, "SIGNATURES_FILE", "nope.json"):
                runcheck._signatures.cache_clear()
                self.assertIsNone(runcheck.ran_no_tests("Ran 0 tests in 0.000s", "", 0))
        finally:
            runcheck._signatures.cache_clear()


class TestRanNoTests(unittest.TestCase):
    def test_each_signature_names_its_zero_test_output(self) -> None:
        for sig, zero, zero_exit, _real, _real_exit in SIGNATURE_CASES:
            with self.subTest(sig=sig):
                self.assertEqual(runcheck.ran_no_tests(zero, "", zero_exit), sig)
                # stderr counts as much as stdout
                self.assertEqual(runcheck.ran_no_tests("", zero, zero_exit), sig)

    def test_a_real_run_with_a_positive_count_is_never_named(self) -> None:
        for sig, _zero, _zero_exit, real, real_exit in SIGNATURE_CASES:
            with self.subTest(sig=sig):
                self.assertIsNone(runcheck.ran_no_tests(real, "", real_exit))

    def test_a_positive_count_anywhere_wins_over_a_zero_line(self) -> None:
        mixed = "Ran 0 tests in 0.000s\n" + "============ 2 passed in 0.1s ============\n"
        self.assertIsNone(runcheck.ran_no_tests(mixed, "", 0))
        self.assertIsNone(runcheck.ran_no_tests("# tests 0\n", "  3 passing (2ms)\n", 0))

    def test_an_exit_code_outside_the_signature_is_not_named(self) -> None:
        self.assertIsNone(runcheck.ran_no_tests("No tests found, exiting with code 1", "", 1))
        self.assertIsNone(runcheck.ran_no_tests("# tests 0\n", "", 1))
        self.assertIsNone(runcheck.ran_no_tests("no tests ran in 0.01s", "", 2))

    def test_pytest_and_unittest_exit_five(self) -> None:
        self.assertEqual(runcheck.ran_no_tests("no tests ran in 0.01s", "", 5), "pytest")
        self.assertEqual(runcheck.ran_no_tests("Ran 0 tests in 0.000s\n\nNO TESTS RAN", "", 5),
                         "unittest")

    def test_unittest_before_312_exits_zero(self) -> None:
        self.assertEqual(runcheck.ran_no_tests("Ran 0 tests in 0.000s\n\nOK", "", 0), "unittest")

    def test_pytest_all_deselected_is_exit_five_only(self) -> None:
        text = "============ 1 deselected in 0.00s ============\n"
        self.assertEqual(runcheck.ran_no_tests(text, "", 5), "pytest-deselected")
        self.assertIsNone(runcheck.ran_no_tests(text, "", 0))

    def test_go_cover_lines_count_as_a_real_run(self) -> None:
        out = ("ok  \texample.com/m/pkg\t0.123s\tcoverage: 80.0% of statements\n"
               "?   \texample.com/m/cmd\t[no test files]\n")
        self.assertIsNone(runcheck.ran_no_tests(out, "", 0))
        cached = "ok  \texample.com/m/pkg\t(cached)\tcoverage: 80.0% of statements\n" \
                 "?   \texample.com/m/cmd\t[no test files]\n"
        self.assertIsNone(runcheck.ran_no_tests(cached, "", 0))

    def test_go_no_tests_to_run_is_not_a_positive(self) -> None:
        out = "ok  \texample.com/m/pkg\t0.002s [no tests to run]\n"
        self.assertEqual(runcheck.ran_no_tests(out, "", 0), "go")

    def test_go_pattern_is_anchored(self) -> None:
        self.assertIsNone(runcheck.ran_no_tests("the docs mention [no test files]\n", "", 0))

    def test_ansi_colour_is_ignored(self) -> None:
        pytest = "\x1b[33m============ \x1b[33mno tests ran\x1b[0m\x1b[33m in 0.01s ============\x1b[0m\n"
        self.assertEqual(runcheck.ran_no_tests(pytest, "", 5), "pytest")
        jest = "\x1b[1mNo tests found, exiting with code 0\x1b[22m\n"
        self.assertEqual(runcheck.ran_no_tests("", jest, 0), "jest")
        real = "\x1b[32m============ 3 passed in 0.1s ============\x1b[0m\nRan 0 tests in 0s\n"
        self.assertIsNone(runcheck.ran_no_tests(real, "", 0))

    def test_patterns_are_anchored(self) -> None:
        self.assertIsNone(runcheck.ran_no_tests("the doc says Ran 0 tests in 0s", "", 0))
        self.assertIsNone(runcheck.ran_no_tests("we had 10 passing (4ms)", "", 0))
        self.assertIsNone(runcheck.ran_no_tests("# tests 05\n", "", 0))


NPM_ENOENT = (
    "npm error code ENOENT\n"
    "npm error syscall open\n"
    "npm error path {root}/package.json\n"
    "npm error errno -2\n"
    "npm error enoent Could not read package.json: Error: ENOENT: no such file or "
    "directory, open '{root}/package.json'\n"
    "npm error enoent This is related to npm not being able to find a file.\n"
)


class TestMissingPaths(unittest.TestCase):
    def test_the_study_gallery_npm_error(self) -> None:
        text = NPM_ENOENT.format(root="/work/app")
        self.assertEqual(runcheck.missing_paths(text), ["/work/app/package.json"])
        self.assertTrue(runcheck.is_missing_manifest(text))

    def test_python_cannot_open_its_script(self) -> None:
        text = "python3: can't open file '/work/app/tests/run.py': [Errno 2] No such file or directory\n"
        self.assertEqual(runcheck.missing_paths(text), ["/work/app/tests/run.py"])

    def test_a_shell_style_line(self) -> None:
        self.assertEqual(runcheck.missing_paths("cat: src/a.txt: No such file or directory"),
                         ["src/a.txt"])
        self.assertEqual(runcheck.missing_paths("bash: ./run.sh: No such file or directory"),
                         ["./run.sh"])

    def test_a_python_file_not_found_error(self) -> None:
        text = "FileNotFoundError: [Errno 2] No such file or directory: 'data/out.csv'"
        self.assertEqual(runcheck.missing_paths(text), ["data/out.csv"])

    def test_no_module_named_is_not_a_path(self) -> None:
        self.assertEqual(runcheck.missing_paths("ModuleNotFoundError: No module named 'app'"), [])
        self.assertFalse(runcheck.is_missing_manifest("No module named 'app'"))

    def test_windows_style_messages(self) -> None:
        node = "Error: ENOENT: no such file or directory, open 'C:\\work\\app\\package.json'"
        self.assertEqual(runcheck.missing_paths(node), ["C:\\work\\app\\package.json"])
        # Python prints the path through repr(), doubling each backslash.
        py = "python.exe: can't open file 'C:\\\\work\\\\app\\\\run.py': [Errno 2] No such file or directory"
        self.assertEqual(runcheck.missing_paths(py), ["C:\\work\\app\\run.py"])

    def test_node_cannot_find_a_module_path(self) -> None:
        text = "Error: Cannot find module '/work/app/scripts/e2e.js'\n    at Module._resolve"
        self.assertEqual(runcheck.missing_paths(text), ["/work/app/scripts/e2e.js"])
        self.assertEqual(runcheck.missing_paths("Error: Cannot find module './lib/x'"),
                         ["./lib/x"])

    def test_a_bare_package_name_is_not_a_path(self) -> None:
        self.assertEqual(runcheck.missing_paths("Error: Cannot find module 'express'"), [])
        self.assertEqual(runcheck.missing_paths("Error: Cannot find module '@scope/pkg'"), [])

    def test_a_bare_module_named_in_argv_counts(self) -> None:
        text = "Error: Cannot find module 'e2e'"
        self.assertEqual(runcheck.missing_paths(text, argv=["node", "e2e"]), ["e2e"])

    def test_pytest_file_or_directory_not_found(self) -> None:
        text = "ERROR: file or directory not found: tests/test_login.py\n"
        self.assertEqual(runcheck.missing_paths(text), ["tests/test_login.py"])

    def test_an_ambiguous_path_with_spaces_is_not_extracted(self) -> None:
        self.assertEqual(runcheck.missing_paths("cat: my dir/a.txt: No such file or directory"), [])
        self.assertEqual(runcheck.missing_paths("cat: a.txt: No such file or directory"), ["a.txt"])
        self.assertEqual(runcheck.missing_paths("  oops x y.txt: No such file or directory"), [])

    def test_each_path_once(self) -> None:
        text = NPM_ENOENT.format(root="/r") * 2
        self.assertEqual(runcheck.missing_paths(text), ["/r/package.json"])


class TestRelativize(unittest.TestCase):
    def test_under_the_root(self) -> None:
        self.assertEqual(runcheck.relativize("/work/app/package.json", "/work/app"), "package.json")
        self.assertEqual(runcheck.relativize("/work/app/e2e/a.ts", "/work/app/"), "e2e/a.ts")

    def test_relative_paths_are_relative_to_the_root(self) -> None:
        self.assertEqual(runcheck.relativize("package.json", "/work/app"), "package.json")
        self.assertEqual(runcheck.relativize("./src/x.py", "/work/app"), "src/x.py")

    def test_dot_dot_segments_are_normalized(self) -> None:
        self.assertEqual(runcheck.relativize("/r/web/../src/a.ts", "/r"), "src/a.ts")
        self.assertEqual(runcheck.relativize("src/../lib/a.ts", "/r"), "lib/a.ts")
        self.assertIsNone(runcheck.relativize("/r/../etc/x", "/r"))
        self.assertEqual(runcheck.relativize("C:\\r\\web\\..\\src\\a.ts", "C:\\r"), "src/a.ts")

    def test_a_symlinked_path_matches_its_realpath_root(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(os.path.realpath(tmp), "real")
            os.makedirs(os.path.join(real, "src"))
            link = os.path.join(os.path.realpath(tmp), "link")
            os.symlink(real, link)
            # the message names the symlinked form; the root is the real one
            self.assertEqual(runcheck.relativize(link + "/src/missing.json", real),
                             "src/missing.json")

    def test_outside_the_root_is_none(self) -> None:
        self.assertIsNone(runcheck.relativize("/etc/hosts", "/work/app"))
        self.assertIsNone(runcheck.relativize("/work/application/x", "/work/app"))
        self.assertIsNone(runcheck.relativize("../other/x", "/work/app"))
        self.assertIsNone(runcheck.relativize("/work/app", "/work/app"))

    def test_windows_paths(self) -> None:
        self.assertEqual(runcheck.relativize("C:\\work\\app\\package.json", "C:\\work\\app"),
                         "package.json")
        self.assertEqual(runcheck.relativize("c:\\Work\\App\\src\\x.ts", "C:\\work\\app"),
                         "src/x.ts")
        self.assertIsNone(runcheck.relativize("D:\\work\\app\\x", "C:\\work\\app"))
        self.assertEqual(runcheck.relativize("src\\x.ts", "C:\\work\\app"), "src/x.ts")


class TestScopeOwner(unittest.TestCase):
    TASKS = [
        {"id": "shell-login", "write_scope": ["package.json", "src/app/**"]},
        {"id": "e2e", "write_scope": ["e2e/*.spec.ts"]},
        {"id": "survey", "write_scope": "read-only"},
    ]

    def test_the_first_covering_task_is_named(self) -> None:
        self.assertEqual(runcheck.scope_owner("package.json", self.TASKS), "shell-login")
        self.assertEqual(runcheck.scope_owner("src/app/page.tsx", self.TASKS), "shell-login")
        self.assertEqual(runcheck.scope_owner("e2e/login.spec.ts", self.TASKS), "e2e")

    def test_uncovered_paths_have_no_owner(self) -> None:
        self.assertIsNone(runcheck.scope_owner("e2e/nested/x.spec.ts", self.TASKS))
        self.assertIsNone(runcheck.scope_owner("README.md", self.TASKS))
        self.assertIsNone(runcheck.scope_owner("anything", []))
        self.assertIsNone(runcheck.scope_owner("anything", None))

    def test_missing_path_owner_reads_both_streams(self) -> None:
        gate = {"verdict": "fail", "exit": 254, "stdout_tail": "",
                "stderr_tail": NPM_ENOENT.format(root="/work/app")}
        found = runcheck.missing_path_owner(gate, "/work/app", self.TASKS)
        self.assertEqual(found, {"path": "package.json", "owner": "shell-login",
                                 "manifest": True, "argv_named": False})

    def test_missing_path_owner_outside_the_root(self) -> None:
        gate = {"verdict": "fail", "exit": 1, "stdout_tail": "",
                "stderr_tail": "cat: /etc/gatekit.conf: No such file or directory"}
        found = runcheck.missing_path_owner(gate, "/work/app", self.TASKS)
        self.assertEqual(found, {"path": "/etc/gatekit.conf", "owner": None,
                                 "manifest": False, "argv_named": False})

    def test_a_manifest_refusal_names_package_json(self) -> None:
        gate = {"verdict": "fail", "exit": 254, "stdout_tail": "",
                "stderr_tail": "npm error enoent Could not read package.json: Error: ENOENT: "
                               "no such file or directory, open '/work/app/.npmrc'\n"
                               "npm error enoent Error: ENOENT: no such file or directory, "
                               "open '/work/app/package.json'\n"}
        found = runcheck.missing_path_owner(gate, "/work/app", [])
        self.assertEqual(found["path"], "package.json")
        self.assertTrue(found["manifest"])
        bare = {"verdict": "fail", "exit": 254, "stdout_tail": "",
                "stderr_tail": "npm error enoent Could not read package.json\n"
                               "cat: other.txt: No such file or directory\n"}
        self.assertEqual(runcheck.missing_path_owner(bare, "/work/app", [])["path"], "package.json")

    def test_argv_named_is_reported(self) -> None:
        gate = {"verdict": "fail", "exit": 127, "stdout_tail": "",
                "stderr_tail": "bash: scripts/e2e.sh: No such file or directory\n"}
        tasks = [{"id": "e2e", "write_scope": ["scripts/**"]}]
        found = runcheck.missing_path_owner(gate, "/work/app", tasks,
                                            argv=["bash", "scripts/e2e.sh"])
        self.assertEqual((found["path"], found["owner"], found["argv_named"]),
                         ("scripts/e2e.sh", "e2e", True))
        self.assertFalse(runcheck.missing_path_owner(gate, "/work/app", tasks,
                                                     argv=["bash", "-c", "x"])["argv_named"])

    def test_a_program_under_a_dependency_dir(self) -> None:
        tasks = [{"id": "shell", "write_scope": ["package.json", "src/**"]},
                 {"id": "py", "write_scope": ["pyproject.toml"]}]
        dep = runcheck.dependency_program("./node_modules/.bin/playwright", "/work/app", tasks)
        self.assertEqual((dep["dir"], dep["manifest"], dep["owner"]),
                         ("node_modules", "package.json", "shell"))
        dep = runcheck.dependency_program(".venv/bin/pytest", "/work/app", tasks)
        self.assertEqual((dep["dir"], dep["manifest"], dep["owner"]),
                         (".venv", "pyproject.toml", "py"))
        dep = runcheck.dependency_program("web/node_modules/.bin/vite", "/work/app", tasks)
        self.assertEqual((dep["manifest"], dep["owner"]), ("web/package.json", None))
        dep = runcheck.dependency_program("venv/bin/pytest", "/work/app", [])
        self.assertEqual((dep["dir"], dep["owner"]), ("venv", None))
        self.assertIsNone(runcheck.dependency_program("bin/run-e2e", "/work/app", tasks))
        self.assertIsNone(runcheck.dependency_program("playwright", "/work/app", tasks))

    def test_dependency_dirs_are_ones_the_fingerprint_skips(self) -> None:
        from gatekit import contract
        self.assertTrue(set(runcheck.DEPENDENCY_MANIFESTS) <= contract.FINGERPRINT_SKIP_DIRS)

    def test_interpreters(self) -> None:
        for prog in ("bash", "/bin/sh", "zsh", "node", "python3", "/usr/bin/python3.12",
                     "python.exe", "ruby", "deno", "bun", "tsx", "ts-node"):
            self.assertTrue(runcheck.is_interpreter(prog), prog)
        for prog in ("npm", "npx", "pytest", "nonexistentprog", "jest", ""):
            self.assertFalse(runcheck.is_interpreter(prog), prog)

    def test_nothing_extracted_is_none(self) -> None:
        gate = {"verdict": "fail", "exit": 1, "stdout_tail": "1 failed", "stderr_tail": ""}
        self.assertIsNone(runcheck.missing_path_owner(gate, "/work/app", self.TASKS))


class TestGradingFiles(unittest.TestCase):
    """ADR-0023: the files a command names that do the judging."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        os.makedirs(os.path.join(self.root, "tests"))
        os.makedirs(os.path.join(self.root, "scripts"))
        for rel, body in (("tests/test_a.py", "a"), ("scripts/e2e.sh", "e"),
                          ("e2e.spec.ts", "s")):
            with open(os.path.join(self.root, rel), "w") as h:
                h.write(body)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def files(self, argv):
        return runcheck.grading_files(argv, self.root)

    def test_a_script_as_argv0(self) -> None:
        self.assertEqual(self.files(["./scripts/e2e.sh", "--fast"]), ["scripts/e2e.sh"])
        self.assertEqual(self.files(["scripts/e2e.sh"]), ["scripts/e2e.sh"])

    def test_a_spec_path_argument(self) -> None:
        self.assertEqual(self.files(["npx", "playwright", "test", "e2e.spec.ts"]),
                         ["e2e.spec.ts"])
        self.assertEqual(self.files(["python3", "-m", "pytest", "tests/test_a.py::test_x", "-q"]),
                         ["tests/test_a.py"])
        self.assertEqual(self.files(["python3", os.path.join(self.root, "tests", "test_a.py")]),
                         ["tests/test_a.py"])

    def write(self, rel: str, body: str = "x") -> None:
        full = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as h:
            h.write(body)

    def test_files_the_build_edits_are_not_grading_files(self) -> None:
        # F2: a brownfield check names the code it inspects; the build edits
        # or creates those files legitimately, so they do not judge anything.
        for rel in ("src/app.py", "src/x.js", "src/app.js", "src/index.ts", "app.db",
                    "dist/index.html", "scripts/e2e.sh"):
            self.write(rel)
        for argv in (["grep", "-q", "print", "src/app.py"],
                     ["eslint", "src/x.js"],
                     ["node", "--check", "src/app.js"],
                     ["tsc", "src/index.ts"],
                     ["sqlite3", "app.db", "select 1"],
                     ["test", "-f", "dist/index.html"],
                     ["grep", "-q", "<title>", "dist/index.html"],
                     ["python3", "src/app.py", "--selftest"],
                     ["bash", "scripts/e2e.sh"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.files(argv), [])

    def test_test_shaped_files_are_grading_files(self) -> None:
        shapes = ("test/cart.js", "tests/check.py", "src/__tests__/x.js",
                  "spec/models/user_spec.rb", "e2e/login.ts", "pkg/test_util.py",
                  "pkg/util_test.go", "src/app.test.ts", "web/login.spec.ts",
                  "conftest.py", "a/b/test/deep/data.json")
        for rel in shapes:
            self.write(rel)
        for rel in shapes:
            with self.subTest(rel=rel):
                self.assertEqual(self.files(["runner", rel]), [rel])

    def test_build_and_dependency_directories_never_count(self) -> None:
        for rel in ("dist/tests/app.test.js", "node_modules/.bin/vitest",
                    ".venv/bin/pytest", "build/test_x.py"):
            self.write(rel)
        self.assertEqual(self.files(["node", "dist/tests/app.test.js", "build/test_x.py"]), [])
        self.assertEqual(self.files(["./node_modules/.bin/vitest", "run"]), [])
        self.assertEqual(self.files([".venv/bin/pytest"]), [])

    def test_option_values_and_runner_suffixes(self) -> None:
        # F7: `--opt=path`, pytest `[param]` and `file:line` locations.
        self.write("e2e/login.spec.ts")
        self.write("src/app.test.ts")
        self.assertEqual(self.files(["npx", "playwright", "test", "--spec=e2e/login.spec.ts"]),
                         ["e2e/login.spec.ts"])
        self.assertEqual(self.files(["pytest", "tests/test_a.py::test_x[1-2]"]),
                         ["tests/test_a.py"])
        self.assertEqual(self.files(["pytest", "tests/test_a.py[x]"]), ["tests/test_a.py"])
        self.assertEqual(self.files(["npx", "vitest", "src/app.test.ts:12"]),
                         ["src/app.test.ts"])
        self.assertEqual(self.files(["npx", "jest", "src/app.test.ts:12:5"]),
                         ["src/app.test.ts"])
        self.assertEqual(self.files(["runner", "--config=jest.config.js", "--fast"]), [])

    def test_the_patterns_come_from_the_data_file(self) -> None:
        data = runcheck.grading_patterns()
        self.assertIn("tests", data["dirs"])
        self.assertIn("*.spec.*", data["basenames"])
        self.assertIn("node_modules", data["exclude_dirs"])

    def test_a_bare_program_is_not_a_grading_file(self) -> None:
        # Even when a file of that name sits in the root.
        with open(os.path.join(self.root, "pytest"), "w") as h:
            h.write("x")
        self.assertEqual(self.files(["pytest"]), [])
        self.assertEqual(self.files(["npm", "test"]), [])

    def test_outside_the_root_and_dot_dot(self) -> None:
        outside = os.path.join(os.path.dirname(self.root), "elsewhere.py")
        self.assertEqual(self.files(["python3", outside, "/etc/hosts"]), [])
        self.assertEqual(self.files(["python3", "../x.py", "tests/../../x.py"]), [])
        self.assertEqual(self.files(["python3", "tests/../tests/test_a.py"]), ["tests/test_a.py"])

    def test_a_symlink_out_of_the_root(self) -> None:
        import tempfile
        with tempfile.NamedTemporaryFile("w", delete=False) as h:
            h.write("x")
        try:
            os.symlink(h.name, os.path.join(self.root, "tests", "link.py"))
            self.assertEqual(self.files(["python3", "tests/link.py"]), [])
        finally:
            os.unlink(h.name)

    def test_missing_files_and_directories(self) -> None:
        self.assertEqual(self.files(["python3", "tests/nope.py", "tests", "."]), [])

    def test_the_plugin_root_token_is_expanded(self) -> None:
        plugin = os.path.join(self.root, "plug")
        os.makedirs(os.path.join(plugin, ".claude-plugin"))
        with open(os.path.join(plugin, ".claude-plugin", "plugin.json"), "w") as h:
            h.write("{}")
        with open(os.path.join(plugin, "test_check.py"), "w") as h:
            h.write("x")
        old = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = plugin
        try:
            self.assertEqual(self.files(["python3", "${CLAUDE_PLUGIN_ROOT}/test_check.py"]),
                             ["plug/test_check.py"])
        finally:
            if old is None:
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            else:
                os.environ["CLAUDE_PLUGIN_ROOT"] = old

    def test_each_once_and_hashed(self) -> None:
        hashes = runcheck.grading_hashes(["./scripts/e2e.sh", "./scripts/e2e.sh",
                                          "tests/test_a.py"], self.root)
        import hashlib
        self.assertEqual(hashes, {"scripts/e2e.sh": hashlib.sha256(b"e").hexdigest(),
                                  "tests/test_a.py": hashlib.sha256(b"a").hexdigest()})

    def test_a_large_file_hashes_in_chunks(self) -> None:
        import hashlib
        body = b"x" * (3 * 1024 * 1024 + 7)
        with open(os.path.join(self.root, "tests", "test_big.py"), "wb") as h:
            h.write(body)
        hashes = runcheck.grading_hashes(["pytest", "tests/test_big.py"], self.root)
        self.assertEqual(hashes, {"tests/test_big.py": hashlib.sha256(body).hexdigest()})
        self.assertEqual(runcheck.changed_grading(hashes, self.root), [])

    def test_never_raises(self) -> None:
        self.assertEqual(runcheck.grading_hashes(None, self.root), {})
        self.assertEqual(runcheck.grading_hashes([3, None, "\x00bad"], self.root), {})


if __name__ == "__main__":
    unittest.main()
