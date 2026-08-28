from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LegacyAuditTests(unittest.TestCase):
    def test_audit_covers_every_legacy_file_and_branch_ref(self) -> None:
        report = json.loads(
            (ROOT / "docs/legacy-audit.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["component_audit_complete"])
        self.assertEqual(report["tracked_file_count"], 509)
        self.assertEqual(len(report["files"]), 509)
        self.assertEqual(len({row["path"] for row in report["files"]}), 509)
        refs = [ref for row in report["branches"] for ref in row["refs"]]
        self.assertEqual(len(refs), 12)
        self.assertEqual(len(set(refs)), 12)

    def test_audit_preserves_failures_and_live_limitations(self) -> None:
        report = json.loads(
            (ROOT / "docs/legacy-audit.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["baseline"]["tests_passed"], 2512)
        self.assertEqual(report["baseline"]["live_operational_sources"], 0)
        failed = [row for row in report["branches"] if row["test_status"] == "FAIL"]
        self.assertEqual([row["head"] for row in failed], ["7a74058"])
        self.assertEqual(failed[0]["passing_tests"], 26)

    def test_every_file_has_a_terminal_disposition_and_reason(self) -> None:
        report = json.loads(
            (ROOT / "docs/legacy-audit.json").read_text(encoding="utf-8")
        )
        for row in report["files"]:
            self.assertTrue(row["disposition"])
            self.assertNotIn("DEFERRED", row["disposition"])
            self.assertTrue(row["reason"])


if __name__ == "__main__":
    unittest.main()
