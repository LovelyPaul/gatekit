"""Tests for plugin/spec-kit/design-antipatterns.json (ADR-0017 decision 9).

This file is read as prose by the verify evaluator's prompt, not by any
gatekit module — there is no merge or derive logic to unit test the way
presets/design/ has. What is worth pinning here is the data's own shape:
valid JSON, unique ids, and every row carrying the fields a human or an
evaluator would need to act on it (a name, a rule, evidence for where the
pattern came from). A malformed row here would silently degrade to "the
evaluator prompt cites a file that doesn't make sense," which nothing else
in the test suite would catch.
"""
from __future__ import annotations

import json
import pathlib
import unittest

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
ANTIPATTERNS_PATH = PLUGIN_DIR / "spec-kit" / "design-antipatterns.json"


class TestDesignAntipatterns(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(ANTIPATTERNS_PATH.read_text(encoding="utf-8"))

    def test_file_exists_and_parses(self) -> None:
        self.assertIsInstance(self.data, dict)

    def test_has_version_and_pattern_list(self) -> None:
        self.assertIn("version", self.data)
        self.assertIsInstance(self.data.get("patterns"), list)
        self.assertGreater(len(self.data["patterns"]), 0)

    def test_every_pattern_has_required_fields(self) -> None:
        required = {"id", "name", "rule", "evidence"}
        for pattern in self.data["patterns"]:
            self.assertTrue(required.issubset(pattern.keys()), pattern)
            for field in required:
                self.assertTrue(
                    isinstance(pattern[field], str) and pattern[field].strip(),
                    f"{field} must be a non-empty string: {pattern}",
                )

    def test_pattern_ids_are_unique(self) -> None:
        ids = [p["id"] for p in self.data["patterns"]]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_pattern_ids_follow_the_ap_prefix(self) -> None:
        for pattern in self.data["patterns"]:
            self.assertRegex(pattern["id"], r"^AP\d+$")

    def test_at_least_one_pattern_is_observed_not_only_seeded(self) -> None:
        """ADR-0017's implementation notes: this list is seeded from a
        reviewed conversation, but is expected to grow from real trials the
        way presets do — gk-todo's no-styling failure is the first such
        entry, tagged distinctly from the seed entries."""
        observed = [p for p in self.data["patterns"] if p["evidence"].startswith("observed:")]
        self.assertGreaterEqual(len(observed), 1)


if __name__ == "__main__":
    unittest.main()
