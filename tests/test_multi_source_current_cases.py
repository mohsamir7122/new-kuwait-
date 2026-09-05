from __future__ import annotations

import unittest

from kubo.multi_source_aggregation import ClaimPolicy, aggregate_claim, observation_from_dict


DECISION_AT = "2026-09-05T04:00:00+03:00"


def obs(
    observation_id: str,
    security_code: str,
    ticker: str,
    claim_key: str,
    value,
    unit: str,
    source_family: str,
    source_role: str,
    *,
    session_date: str | None = "2026-09-03",
    origin_family: str | None = None,
):
    return observation_from_dict(
        {
            "observation_id": observation_id,
            "security_code": security_code,
            "ticker": ticker,
            "claim_key": claim_key,
            "value": value,
            "unit": unit,
            "source_id": observation_id,
            "source_family": source_family,
            "origin_family": origin_family or source_family,
            "source_role": source_role,
            "session_date": session_date,
            "as_of_date": session_date,
            "first_available_at": "2026-09-03T14:00:00+03:00",
            "captured_at": "2026-09-03T14:00:00+03:00",
            "legal_access": True,
            "semantic_complete": True,
            "timestamp_complete": True,
            "value_unlocked": True,
            "evidence_ref": f"evidence:{observation_id}",
        }
    )


def numeric_policy(
    claim_key: str,
    unit: str,
    *,
    target_session_date: str | None = "2026-09-03",
    minimum_independent_families: int = 2,
) -> ClaimPolicy:
    return ClaimPolicy(
        claim_key=claim_key,
        kind="NUMBER",
        unit=unit,
        allowed_roles=(
            "ISSUER_PRIMARY",
            "REGULATOR_OR_EXCHANGE",
            "LICENSED_MARKET_DATA",
            "SECONDARY_MARKET_DATA",
            "FINANCIAL_CONTEXT",
        ),
        minimum_independent_families=minimum_independent_families,
        single_source_authority_roles=("ISSUER_PRIMARY", "REGULATOR_OR_EXCHANGE"),
        absolute_tolerance=0.01,
        relative_tolerance=0.0001,
        requires_session_date=target_session_date is not None,
        target_session_date=target_session_date,
    )


class CurrentKuwaitAggregationCases(unittest.TestCase):
    def test_aznoula_consensus_resolves_140_and_flags_stale_outlier(self) -> None:
        rows = [
            obs("investing-aznoula-close", "826", "AZNOULA", "close_fils", 140, "FILS", "investing", "SECONDARY_MARKET_DATA"),
            obs("argaam-aznoula-close", "826", "AZNOULA", "close_fils", 140, "FILS", "argaam", "FINANCIAL_CONTEXT"),
            obs("decypha-aznoula-close", "826", "AZNOULA", "close_fils", 140, "FILS", "decypha", "SECONDARY_MARKET_DATA"),
            obs("mubasher-aznoula-stale-reference", "826", "AZNOULA", "close_fils", 146, "FILS", "mubasher", "SECONDARY_MARKET_DATA"),
        ]
        result = aggregate_claim(
            observations=rows,
            policy=numeric_policy("close_fils", "FILS"),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["resolved"]["value"], 140)
        self.assertEqual(result["independent_family_count"], 4)
        self.assertEqual(
            result["outlier_observation_ids"], ["mubasher-aznoula-stale-reference"]
        )

    def test_alimtiaz_current_share_count_wins_over_stale_profile(self) -> None:
        rows = [
            obs(
                "issuer-alimtiaz-current-shares",
                "252",
                "ALIMTIAZ",
                "issued_shares",
                1_031_573_930,
                "SHARES",
                "alimtiaz_issuer",
                "ISSUER_PRIMARY",
                session_date=None,
            ),
            obs(
                "decypha-alimtiaz-current-shares",
                "252",
                "ALIMTIAZ",
                "issued_shares",
                1_031_573_930,
                "SHARES",
                "decypha",
                "SECONDARY_MARKET_DATA",
                session_date=None,
            ),
            obs(
                "mubasher-alimtiaz-old-shares",
                "252",
                "ALIMTIAZ",
                "issued_shares",
                1_133_617_350,
                "SHARES",
                "mubasher",
                "SECONDARY_MARKET_DATA",
                session_date=None,
            ),
        ]
        result = aggregate_claim(
            observations=rows,
            policy=numeric_policy(
                "issued_shares", "SHARES", target_session_date=None
            ),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["resolved"]["value"], 1_031_573_930)
        self.assertEqual(
            result["outlier_observation_ids"], ["mubasher-alimtiaz-old-shares"]
        )

    def test_catt_close_isolated_from_stale_metadata_on_same_webpage(self) -> None:
        rows = [
            obs("investing-cattl-close", "701", "CATTL", "close_fils", 176, "FILS", "investing", "SECONDARY_MARKET_DATA"),
            obs("zonebourse-cattl-close", "701", "CATTL", "close_fils", 176, "FILS", "zonebourse", "SECONDARY_MARKET_DATA"),
            obs("aletihad-cattl-close", "701", "CATTL", "close_fils", 176, "FILS", "aletihad", "FINANCIAL_CONTEXT"),
        ]
        result = aggregate_claim(
            observations=rows,
            policy=numeric_policy("close_fils", "FILS"),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["resolved"]["value"], 176)
        self.assertEqual(result["resolved"]["resolution_basis"], "MULTI_SOURCE_CONSENSUS")

    def test_free_float_can_resolve_from_semantically_complete_reports_portal(self) -> None:
        rows = [
            obs(
                "boursa-reports-aznoula-free-float",
                "826",
                "AZNOULA",
                "free_float_pct",
                49.19,
                "PERCENT",
                "boursa_reports_portal",
                "REGULATOR_OR_EXCHANGE",
                session_date=None,
            )
        ]
        result = aggregate_claim(
            observations=rows,
            policy=numeric_policy(
                "free_float_pct", "PERCENT", target_session_date=None
            ),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["resolved"]["value"], 49.19)
        self.assertEqual(result["resolved"]["resolution_basis"], "SINGLE_AUTHORITY_SOURCE")


if __name__ == "__main__":
    unittest.main()
