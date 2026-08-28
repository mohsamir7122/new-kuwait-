from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from kubo.cli import main
from kubo.hashing import sha256_bytes
from kubo.local_analysis import analyze_local_bundle, write_local_analysis


def _bundle(root: Path) -> tuple[Path, dict[str, object]]:
    bundle = root / "bundle"
    raw = bundle / "raw"
    raw.mkdir(parents=True)
    evidence_content = b"synthetic local evidence\n"
    evidence_path = raw / "evidence.txt"
    evidence_path.write_bytes(evidence_content)
    digest = sha256_bytes(evidence_content)
    prices = [
        {
            "date": f"2026-08-{day:02d}",
            "close_fils": close,
            "volume": volume,
            "turnover_kwd": volume * close / 1000,
            "evidence_sha256": digest,
        }
        for day, close, volume in (
            (20, 100, 1000),
            (21, 102, 1100),
            (22, 101, 900),
            (23, 103, 1200),
            (24, 105, 1500),
        )
    ]
    request: dict[str, object] = {
        "schema_version": "1.0",
        "analysis_id": "local-test-001",
        "decision_at": "2026-08-24T15:00:00+03:00",
        "capture_mode": "PROSPECTIVE",
        "identity": {
            "security_code": "101",
            "ticker": "TEST",
            "isin": "KW0000000001",
            "name_ar": "اختبار",
            "name_en": "Test",
            "board": "cash",
            "market_segment": "MAIN",
            "currency": "KWD",
            "valid_from": "2020-01-01",
            "valid_to": None,
            "listing_status": "TRADING",
            "evidence_sha256": digest,
        },
        "evidence": [{"path": "raw/evidence.txt", "sha256": digest}],
        "prices": prices,
        "events": [
            {
                "event_id": "event-1",
                "security_code": "101",
                "source_id": "issuer",
                "source_role": "ISSUER_PRIMARY",
                "event_type": "CONTRACT",
                "direction": "POSITIVE",
                "novelty": 0.8,
                "event_at": "2026-08-23T10:00:00+03:00",
                "published_at": "2026-08-23T10:00:00+03:00",
                "first_available_at": "2026-08-23T10:00:00+03:00",
                "captured_at": "2026-08-23T11:00:00+03:00",
                "content_hash": digest,
                "evidence_hash": digest,
                "relation_type": "STANDALONE",
                "original_event_id": None,
                "raw_text": "synthetic event",
            }
        ],
        "fundamentals": {
            "current": {
                "revenue": 120,
                "net_income": 20,
                "operating_cash_flow": 25,
                "total_debt": 30,
                "equity": 100,
            },
            "prior": {
                "revenue": 100,
                "net_income": 10,
                "operating_cash_flow": 8,
                "total_debt": 40,
                "equity": 90,
            },
            "evidence_sha256s": [digest],
        },
        "sentiment": [
            {
                "origin_id": "origin-1",
                "author_id": "author-1",
                "tone": 0.8,
                "author_reliability": 0.7,
                "evidence_sha256": digest,
            },
            {
                "origin_id": "origin-2",
                "author_id": "author-2",
                "tone": 0.5,
                "author_reliability": 0.6,
                "evidence_sha256": digest,
            },
        ],
    }
    (bundle / "request.json").write_text(
        json.dumps(request, ensure_ascii=False),
        encoding="utf-8",
    )
    return bundle, request


class LocalAnalysisTests(unittest.TestCase):
    def test_end_to_end_report_is_descriptive_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle, _ = _bundle(Path(directory))
            report = analyze_local_bundle(bundle)

        self.assertEqual(report["status"], "PASS_RESEARCH_SUMMARY")
        self.assertEqual(report["security"]["security_code"], "101")
        self.assertEqual(report["price_session_count"], 5)
        self.assertEqual(report["event_count"], 1)
        self.assertFalse(report["claim_boundaries"]["recommendation"])
        self.assertFalse(report["claim_boundaries"]["probability"])
        self.assertRegex(report["report_sha256"], r"^[0-9a-f]{64}$")

    def test_tampered_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle, _ = _bundle(Path(directory))
            (bundle / "raw/evidence.txt").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                analyze_local_bundle(bundle)

    def test_future_price_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle, request = _bundle(Path(directory))
            request["prices"][-1]["date"] = "2026-08-25"
            (bundle / "request.json").write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "after decision"):
                analyze_local_bundle(bundle)

    def test_prospective_late_event_capture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle, request = _bundle(Path(directory))
            request["events"][0]["captured_at"] = "2026-08-25T11:00:00+03:00"
            (bundle / "request.json").write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "feature validation failed"):
                analyze_local_bundle(bundle)

    def test_output_is_atomic_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, _ = _bundle(root)
            output = root / "result"
            write_local_analysis(bundle, output)
            first = (output / "report.json").read_bytes()
            with self.assertRaises(RuntimeError):
                write_local_analysis(bundle, output)
            self.assertEqual((output / "report.json").read_bytes(), first)

    def test_cli_writes_report_and_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, _ = _bundle(root)
            output = root / "result"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "analyze-local",
                        "--bundle",
                        str(bundle),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "PASS_RESEARCH_SUMMARY")
            self.assertTrue((output / "manifest.json").is_file())

    def test_request_and_report_match_published_schemas(self) -> None:
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            bundle, request = _bundle(Path(directory))
            report = analyze_local_bundle(bundle)
        request_schema = json.loads(
            (project / "schemas/local-analysis-request.schema.json").read_text(encoding="utf-8")
        )
        report_schema = json.loads(
            (project / "schemas/local-analysis-report.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(request_schema).validate(request)
        Draft202012Validator(report_schema).validate(report)


if __name__ == "__main__":
    unittest.main()
