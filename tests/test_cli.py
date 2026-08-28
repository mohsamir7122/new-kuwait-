from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import unittest

from kubo.cli import build_self_check, main


class CliTests(unittest.TestCase):
    def test_self_check_is_truthful_about_runtime_boundaries(self) -> None:
        report = build_self_check()

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["stage"], "CLEAN_CORE")
        self.assertFalse(report["claim_boundaries"]["live_collection"])
        self.assertFalse(report["claim_boundaries"]["prediction"])

    def test_cli_emits_machine_readable_report(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["self-check"])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
