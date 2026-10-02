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
        self.assertEqual(runcheck.ran_no_tests("Ran 0 tests in 0.000s\n\nOK", "", 0), "unittest")

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
                                 "manifest": True})

    def test_missing_path_owner_outside_the_root(self) -> None:
        gate = {"verdict": "fail", "exit": 1, "stdout_tail": "",
                "stderr_tail": "cat: /etc/gatekit.conf: No such file or directory"}
        found = runcheck.missing_path_owner(gate, "/work/app", self.TASKS)
        self.assertEqual(found, {"path": "/etc/gatekit.conf", "owner": None,
                                 "manifest": False})

    def test_nothing_extracted_is_none(self) -> None:
        gate = {"verdict": "fail", "exit": 1, "stdout_tail": "1 failed", "stderr_tail": ""}
        self.assertIsNone(runcheck.missing_path_owner(gate, "/work/app", self.TASKS))


if __name__ == "__main__":
    unittest.main()
