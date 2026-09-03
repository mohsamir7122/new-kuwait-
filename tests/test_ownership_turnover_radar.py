from __future__ import annotations

from datetime import date, timedelta
import unittest

from kubo.ownership_turnover_radar import (
    analyze_ownership_turnover,
    capital_structure_from_dict,
    historical_bar_from_dict,
    ownership_event_from_dict,
    scan_ownership_turnover_universe,
    session_snapshot_from_dict,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
MANIFEST = frozenset({HASH_A, HASH_B, HASH_C, HASH_D})


def ts(day: str, hour: int = 14) -> str:
    return f"{day}T{hour:02d}:00:00+03:00"


def capital(decision_at: str):
    return capital_structure_from_dict(
        {
            "security_code": "657",
            "issued_shares": 119_730_000,
            "free_float_shares": 80_160_000,
            "as_of": ts("2026-06-30"),
            "evidence_hashes": [HASH_A],
        },
        manifest_hashes=MANIFEST,
        decision_at=decision_at,
    )


def bars():
    # Nineteen Kuwait trading sessions through 26 August 2026. The final five
    # reproduce a high-turnover cluster without using later outcomes.
    sessions = []
    cursor = date(2026, 8, 1)
    while cursor <= date(2026, 8, 26):
        if cursor.weekday() not in (4, 5):  # Friday/Saturday weekend
            sessions.append(cursor)
        cursor += timedelta(days=1)
    volumes = [
        700_000,
        760_000,
        800_000,
        820_000,
        790_000,
        750_000,
        810_000,
        780_000,
        770_000,
        830_000,
        760_000,
        790_000,
        800_000,
        820_000,
        4_750_000,
        1_130_000,
        2_860_000,
        8_350_000,
        3_750_000,
    ]
    closes = [
        101,
        100,
        99,
        98,
        99,
        98,
        97,
        96,
        95,
        94,
        93,
        92,
        91,
        90,
        88,
        89.3,
        85.2,
        87.5,
        86.5,
    ]
    output = []
    for session, volume, close in zip(sessions, volumes, closes):
        output.append(
            historical_bar_from_dict(
                {
                    "security_code": "657",
                    "session_date": session.isoformat(),
                    "close_fils": close,
                    "volume": volume,
                    "turnover_kwd": close * volume / 1000,
                    "available_at": ts(session.isoformat(), 14),
                    "captured_at": ts(session.isoformat(), 14),
                    "evidence_hash": HASH_B,
                },
                manifest_hashes=MANIFEST,
            )
        )
    return output


def event(
    *,
    event_id: str,
    canonical_event_id: str | None = None,
    event_type: str = "BENEFICIAL_OWNERSHIP_CHANGE",
    first_available_at: str,
    holder_id: str | None = "holder",
    holder_role: str = "MAJOR_HOLDER",
    previous_pct: float | None = 20,
    current_pct: float | None = 17,
    shares: int | None = None,
    source_role: str = "REGULATOR_OR_EXCHANGE",
):
    return ownership_event_from_dict(
        {
            "event_id": event_id,
            "canonical_event_id": canonical_event_id or event_id,
            "security_code": "657",
            "event_type": event_type,
            "source_role": source_role,
            "holder_id": holder_id,
            "holder_role": holder_role,
            "buyer_id": "buyer" if shares else None,
            "seller_id": holder_id if shares else None,
            "previous_pct": previous_pct,
            "current_pct": current_pct,
            "shares": shares,
            "transaction_price_fils": 70 if shares else None,
            "occurred_at": first_available_at,
            "published_at": first_available_at,
            "first_available_at": first_available_at,
            "captured_at": first_available_at,
            "evidence_hash": HASH_C,
        },
        manifest_hashes=MANIFEST,
    )


class OwnershipTurnoverRadarTests(unittest.TestCase):
    def test_pre_event_cluster_becomes_high_priority_watch_without_direction(self) -> None:
        decision_at = ts("2026-08-30", 8)
        events = [
            event(
                event_id="major-1",
                first_available_at=ts("2026-04-28", 9),
                previous_pct=19.987,
                current_pct=17.836,
            ),
            event(
                event_id="major-2",
                first_available_at=ts("2026-06-04", 9),
                previous_pct=18.921,
                current_pct=14.463,
            ),
            event(
                event_id="insider-1",
                event_type="INSIDER_TRADE",
                first_available_at=ts("2026-05-18", 9),
                holder_role="INSIDER",
                previous_pct=None,
                current_pct=None,
                shares=125_560,
            ),
            event(
                event_id="affiliate-1",
                event_type="AFFILIATE_TRADE",
                first_available_at=ts("2026-05-18", 9),
                holder_role="AFFILIATE",
                previous_pct=None,
                current_pct=None,
                shares=4_230_000,
            ),
        ]
        report = analyze_ownership_turnover(
            security_code="657",
            ticker="FUTUREKID",
            decision_at=decision_at,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            capital_structure=capital(decision_at),
            ownership_events=events,
            historical_bars=bars(),
        )
        self.assertEqual(report["research_status"], "HIGH_PRIORITY_WATCH")
        self.assertEqual(
            report["components"]["ownership_event"],
            "CONFIRMED_MATERIAL_OWNERSHIP_EVENT",
        )
        self.assertEqual(report["components"]["directional_confirmation"], "NOT_OBSERVED")
        self.assertEqual(report["trade_eligibility"], "BLOCKED")
        self.assertIn(
            "CUMULATIVE_MAJOR_HOLDER_REDUCTION_GE_5PP", report["reason_codes"]
        )
        self.assertNotIn("score", report)

    def test_event_published_after_cutoff_is_not_backfilled(self) -> None:
        decision_at = ts("2026-08-30", 8)
        future_block = event(
            event_id="block-future",
            event_type="AGREED_TRADE",
            first_available_at=ts("2026-09-02", 9),
            holder_id=None,
            holder_role="UNKNOWN",
            previous_pct=None,
            current_pct=None,
            shares=34_000_000,
        )
        report = analyze_ownership_turnover(
            security_code="657",
            ticker="FUTUREKID",
            decision_at=decision_at,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            capital_structure=capital(decision_at),
            ownership_events=[future_block],
            historical_bars=bars(),
        )
        self.assertEqual(report["metrics"]["block_shares_180d"], 0)
        self.assertNotEqual(
            report["components"]["ownership_event"],
            "CONFIRMED_CONTROL_RELEVANT_EVENT",
        )

    def test_block_trade_plus_extreme_market_confirmation_is_event_confirmed(self) -> None:
        decision_at = ts("2026-09-02", 13)
        block = event(
            event_id="block-1",
            event_type="AGREED_TRADE",
            first_available_at=ts("2026-09-02", 9),
            holder_id=None,
            holder_role="UNKNOWN",
            previous_pct=None,
            current_pct=None,
            shares=34_000_000,
        )
        snapshot = session_snapshot_from_dict(
            {
                "security_code": "657",
                "session_date": "2026-09-02",
                "market_phase": "CLOSED",
                "previous_close_fils": 90,
                "open_fils": 100,
                "high_fils": 127,
                "low_fils": 98,
                "last_fils": 126,
                "volume": 95_000_000,
                "turnover_kwd": 10_600_000,
                "trade_count": 3000,
                "market_total_volume": 342_500_000,
                "market_total_turnover_kwd": 76_700_000,
                "market_return_pct": -0.0042,
                "sector_return_pct": 0.01,
                "available_at": ts("2026-09-02", 13),
                "captured_at": ts("2026-09-02", 13),
                "evidence_hash": HASH_D,
            },
            manifest_hashes=MANIFEST,
        )
        report = analyze_ownership_turnover(
            security_code="657",
            ticker="FUTUREKID",
            decision_at=decision_at,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            capital_structure=capital(decision_at),
            ownership_events=[block],
            historical_bars=bars(),
            session_snapshot=snapshot,
        )
        self.assertEqual(report["research_status"], "EVENT_CONFIRMED")
        self.assertEqual(
            report["components"]["ownership_event"],
            "CONFIRMED_CONTROL_RELEVANT_EVENT",
        )
        self.assertEqual(
            report["components"]["directional_confirmation"], "POSITIVE_CONFIRMED"
        )
        self.assertIn("FULL_FREE_FLOAT_ROTATION_GE_100PCT", report["reason_codes"])
        self.assertGreater(report["metrics"]["relative_volume_20d"], 10)

    def test_next_session_can_be_positive_with_elevated_reversal_risk(self) -> None:
        decision_at = ts("2026-09-03", 13)
        block = event(
            event_id="block-1",
            event_type="AGREED_TRADE",
            first_available_at=ts("2026-09-02", 9),
            holder_id=None,
            holder_role="UNKNOWN",
            previous_pct=None,
            current_pct=None,
            shares=34_000_000,
        )
        snapshot = session_snapshot_from_dict(
            {
                "security_code": "657",
                "session_date": "2026-09-03",
                "market_phase": "CLOSED",
                "previous_close_fils": 127,
                "open_fils": 135,
                "high_fils": 180,
                "low_fils": 135,
                "last_fils": 156,
                "volume": 125_160_000,
                "turnover_kwd": 19_410_000,
                "trade_count": 5000,
                "market_total_volume": 421_000_000,
                "market_total_turnover_kwd": 97_000_000,
                "market_return_pct": -0.0021,
                "sector_return_pct": 0.003,
                "available_at": ts("2026-09-03", 13),
                "captured_at": ts("2026-09-03", 13),
                "evidence_hash": HASH_D,
            },
            manifest_hashes=MANIFEST,
        )
        report = analyze_ownership_turnover(
            security_code="657",
            ticker="FUTUREKID",
            decision_at=decision_at,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            capital_structure=capital(decision_at),
            ownership_events=[block],
            historical_bars=bars(),
            session_snapshot=snapshot,
        )
        self.assertEqual(
            report["components"]["directional_confirmation"], "POSITIVE_CONFIRMED"
        )
        self.assertEqual(
            report["components"]["continuation_structure"],
            "ELEVATED_REVERSAL_RISK",
        )
        self.assertIn(
            "VOLUME_CLIMAX_OR_DISTRIBUTION_RISK", report["reason_codes"]
        )

    def test_impossible_security_volume_greater_than_market_total_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds market total volume"):
            session_snapshot_from_dict(
                {
                    "security_code": "657",
                    "session_date": "2026-09-03",
                    "market_phase": "CONTINUOUS_TRADING",
                    "previous_close_fils": 100,
                    "open_fils": 100,
                    "high_fils": 101,
                    "low_fils": 99,
                    "last_fils": 100,
                    "volume": 2_000_000,
                    "turnover_kwd": 200_000,
                    "trade_count": 100,
                    "market_total_volume": 1_000_000,
                    "market_total_turnover_kwd": 500_000,
                    "market_return_pct": 0,
                    "sector_return_pct": 0,
                    "available_at": ts("2026-09-03", 10),
                    "captured_at": ts("2026-09-03", 10),
                    "evidence_hash": HASH_D,
                },
                manifest_hashes=MANIFEST,
            )

    def test_conflicting_republish_is_not_silently_reconciled(self) -> None:
        decision_at = ts("2026-08-30", 8)
        first = event(
            event_id="copy-1",
            canonical_event_id="same-event",
            first_available_at=ts("2026-06-04", 9),
            previous_pct=18,
            current_pct=14,
        )
        conflicting = event(
            event_id="copy-2",
            canonical_event_id="same-event",
            first_available_at=ts("2026-06-04", 9),
            previous_pct=18,
            current_pct=10,
            source_role="NEWS_CONTEXT",
        )
        report = analyze_ownership_turnover(
            security_code="657",
            ticker="FUTUREKID",
            decision_at=decision_at,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            capital_structure=capital(decision_at),
            ownership_events=[first, conflicting],
            historical_bars=bars(),
        )
        self.assertEqual(report["research_status"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(report["evidence_status"], "CONFLICT")
        self.assertEqual(report["conflicting_canonical_event_ids"], ["same-event"])

    def test_insider_purchase_is_not_mislabeled_as_supply(self) -> None:
        decision_at = ts("2026-08-30", 8)
        purchase = ownership_event_from_dict(
            {
                "event_id": "insider-buy",
                "canonical_event_id": "insider-buy",
                "security_code": "657",
                "event_type": "INSIDER_TRADE",
                "source_role": "REGULATOR_OR_EXCHANGE",
                "holder_id": "insider",
                "holder_role": "INSIDER",
                "buyer_id": "insider",
                "seller_id": "external-holder",
                "previous_pct": None,
                "current_pct": None,
                "shares": 500_000,
                "transaction_price_fils": 85,
                "occurred_at": ts("2026-08-25", 9),
                "published_at": ts("2026-08-25", 9),
                "first_available_at": ts("2026-08-25", 9),
                "captured_at": ts("2026-08-25", 9),
                "evidence_hash": HASH_C,
            },
            manifest_hashes=MANIFEST,
        )
        report = analyze_ownership_turnover(
            security_code="657",
            ticker="FUTUREKID",
            decision_at=decision_at,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            capital_structure=capital(decision_at),
            ownership_events=[purchase],
            historical_bars=bars(),
        )
        self.assertEqual(
            report["metrics"]["insider_affiliate_supply_event_count_180d"], 0
        )
        self.assertNotIn(
            "INSIDER_OR_AFFILIATE_SUPPLY_CLUSTER", report["reason_codes"]
        )

    def test_universe_scan_ranks_all_cases_without_a_watchlist(self) -> None:
        decision_at = ts("2026-08-30", 8)
        high_case = {
            "security_code": "657",
            "ticker": "FUTUREKID",
            "decision_at": decision_at,
            "capture_mode": "HISTORICAL_POINT_IN_TIME",
            "capital_structure": capital(decision_at),
            "ownership_events": [
                event(
                    event_id="major-1",
                    first_available_at=ts("2026-04-28", 9),
                    previous_pct=20,
                    current_pct=14,
                )
            ],
            "historical_bars": bars(),
        }
        quiet_capital = capital_structure_from_dict(
            {
                "security_code": "100",
                "issued_shares": 1_000_000_000,
                "free_float_shares": 800_000_000,
                "as_of": ts("2026-06-30"),
                "evidence_hashes": [HASH_A],
            },
            manifest_hashes=MANIFEST,
            decision_at=decision_at,
        )
        quiet_rows = []
        for index in range(10):
            day = date(2026, 8, 1) + timedelta(days=index)
            quiet_rows.append(
                historical_bar_from_dict(
                    {
                        "security_code": "100",
                        "session_date": day.isoformat(),
                        "close_fils": 100 + index * 0.1,
                        "volume": 1_000_000,
                        "turnover_kwd": 100_000,
                        "available_at": ts(day.isoformat(), 14),
                        "captured_at": ts(day.isoformat(), 14),
                        "evidence_hash": HASH_B,
                    },
                    manifest_hashes=MANIFEST,
                )
            )
        quiet_case = {
            "security_code": "100",
            "ticker": "QUIET",
            "decision_at": decision_at,
            "capture_mode": "HISTORICAL_POINT_IN_TIME",
            "capital_structure": quiet_capital,
            "ownership_events": [],
            "historical_bars": quiet_rows,
        }
        results = scan_ownership_turnover_universe([quiet_case, high_case])
        self.assertEqual(results[0]["ticker"], "FUTUREKID")
        self.assertEqual(results[0]["investigation_rank"], 1)
        self.assertEqual(results[1]["research_status"], "ABSTAIN")


if __name__ == "__main__":
    unittest.main()
