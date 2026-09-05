from __future__ import annotations

import unittest

from kubo.multi_source_aggregation import (
    ClaimPolicy,
    ProposedInference,
    aggregate_claim,
    aggregate_security_claims,
    observation_from_dict,
)


DECISION_AT = "2026-09-05T04:00:00+03:00"


def observation(
    *,
    observation_id: str,
    security_code: str,
    ticker: str,
    claim_key: str,
    value,
    unit: str,
    source_family: str,
    source_role: str,
    origin_family: str | None = None,
    session_date: str | None = "2026-09-03",
    first_available_at: str = "2026-09-03T14:00:00+03:00",
    legal_access: bool = True,
    semantic_complete: bool = True,
    timestamp_complete: bool = True,
    value_unlocked: bool = True,
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
            "first_available_at": first_available_at,
            "captured_at": first_available_at,
            "legal_access": legal_access,
            "semantic_complete": semantic_complete,
            "timestamp_complete": timestamp_complete,
            "value_unlocked": value_unlocked,
            "evidence_ref": f"evidence:{observation_id}",
        }
    )


def close_policy(claim_key: str = "close_fils") -> ClaimPolicy:
    return ClaimPolicy(
        claim_key=claim_key,
        kind="NUMBER",
        unit="FILS",
        allowed_roles=(
            "LICENSED_MARKET_DATA",
            "SECONDARY_MARKET_DATA",
            "REGULATOR_OR_EXCHANGE",
        ),
        minimum_independent_families=2,
        absolute_tolerance=0.01,
        relative_tolerance=0.0001,
        requires_session_date=True,
        target_session_date="2026-09-03",
    )


class MultiSourceAggregationTests(unittest.TestCase):
    def test_alimtiaz_close_resolves_from_two_independent_sources(self) -> None:
        rows = [
            observation(
                observation_id="investing-alimtiaz-close",
                security_code="ALIMTIAZ",
                ticker="ALIMTIAZ",
                claim_key="close_fils",
                value=75.3,
                unit="FILS",
                source_family="investing",
                source_role="SECONDARY_MARKET_DATA",
            ),
            observation(
                observation_id="aletihad-alimtiaz-close",
                security_code="ALIMTIAZ",
                ticker="ALIMTIAZ",
                claim_key="close_fils",
                value=75.3,
                unit="FILS",
                source_family="aletihad",
                source_role="SECONDARY_MARKET_DATA",
            ),
        ]
        result = aggregate_claim(
            observations=rows,
            policy=close_policy(),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["resolved"]["value"], 75.3)
        self.assertEqual(result["independent_family_count"], 2)

    def test_north_zour_previous_close_conflict_is_not_hidden(self) -> None:
        policy = close_policy("previous_close_fils")
        rows = [
            observation(
                observation_id="investing-aznoula-prev",
                security_code="AZNOULA",
                ticker="AZNOULA",
                claim_key="previous_close_fils",
                value=140,
                unit="FILS",
                source_family="investing",
                source_role="SECONDARY_MARKET_DATA",
            ),
            observation(
                observation_id="mubasher-aznoula-prev",
                security_code="AZNOULA",
                ticker="AZNOULA",
                claim_key="previous_close_fils",
                value=146,
                unit="FILS",
                source_family="mubasher",
                source_role="SECONDARY_MARKET_DATA",
            ),
            observation(
                observation_id="argaam-aznoula-prev",
                security_code="AZNOULA",
                ticker="AZNOULA",
                claim_key="previous_close_fils",
                value=141,
                unit="FILS",
                source_family="argaam",
                source_role="FINANCIAL_CONTEXT",
            ),
        ]
        policy = ClaimPolicy(
            claim_key="previous_close_fils",
            kind="NUMBER",
            unit="FILS",
            allowed_roles=("SECONDARY_MARKET_DATA", "FINANCIAL_CONTEXT"),
            minimum_independent_families=2,
            absolute_tolerance=0.01,
            requires_session_date=True,
            target_session_date="2026-09-03",
        )
        result = aggregate_claim(
            observations=rows,
            policy=policy,
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "CONFLICT")
        self.assertIsNone(result["resolved"])
        self.assertFalse(result["fact_usable"])

    def test_mawashi_official_h1_loss_can_resolve_as_single_authority(self) -> None:
        policy = ClaimPolicy(
            claim_key="h1_parent_net_loss_kwd",
            kind="NUMBER",
            unit="KWD",
            allowed_roles=("ISSUER_PRIMARY", "NEWS_CONTEXT"),
            single_source_authority_roles=("ISSUER_PRIMARY",),
            minimum_independent_families=2,
            absolute_tolerance=1,
        )
        rows = [
            observation(
                observation_id="mawashi-official-h1",
                security_code="CATTL",
                ticker="CATTL",
                claim_key="h1_parent_net_loss_kwd",
                value=1_961_597,
                unit="KWD",
                source_family="mawashi_company",
                source_role="ISSUER_PRIMARY",
                session_date=None,
            )
        ]
        result = aggregate_claim(
            observations=rows,
            policy=policy,
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(
            result["resolved"]["resolution_basis"], "SINGLE_AUTHORITY_SOURCE"
        )

    def test_republished_articles_count_as_one_origin(self) -> None:
        policy = ClaimPolicy(
            claim_key="government_support_kwd",
            kind="NUMBER",
            unit="KWD",
            allowed_roles=("NEWS_CONTEXT",),
            minimum_independent_families=2,
            absolute_tolerance=1,
        )
        rows = [
            observation(
                observation_id="news-copy-1",
                security_code="CATTL",
                ticker="CATTL",
                claim_key="government_support_kwd",
                value=5_400_000,
                unit="KWD",
                source_family="news_a",
                origin_family="mawashi_disclosure_2026_08_17",
                source_role="NEWS_CONTEXT",
                session_date=None,
            ),
            observation(
                observation_id="news-copy-2",
                security_code="CATTL",
                ticker="CATTL",
                claim_key="government_support_kwd",
                value=5_400_000,
                unit="KWD",
                source_family="news_b",
                origin_family="mawashi_disclosure_2026_08_17",
                source_role="NEWS_CONTEXT",
                session_date=None,
            ),
        ]
        result = aggregate_claim(
            observations=rows,
            policy=policy,
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "SINGLE_SOURCE")
        self.assertEqual(result["independent_family_count"], 1)

    def test_wrong_session_is_excluded_instead_of_blended(self) -> None:
        rows = [
            observation(
                observation_id="latest-session",
                security_code="ALIMTIAZ",
                ticker="ALIMTIAZ",
                claim_key="close_fils",
                value=75.3,
                unit="FILS",
                source_family="investing",
                source_role="SECONDARY_MARKET_DATA",
            ),
            observation(
                observation_id="older-session",
                security_code="ALIMTIAZ",
                ticker="ALIMTIAZ",
                claim_key="close_fils",
                value=74.0,
                unit="FILS",
                source_family="archive_vendor",
                source_role="SECONDARY_MARKET_DATA",
                session_date="2026-09-02",
            ),
        ]
        result = aggregate_claim(
            observations=rows,
            policy=close_policy(),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "SINGLE_SOURCE")
        self.assertEqual(result["excluded"][0]["reason"], "STALE_OR_WRONG_SESSION")

    def test_blocked_boursa_page_is_rejected_even_when_value_exists(self) -> None:
        row = observation(
            observation_id="boursa-shell",
            security_code="AZNOULA",
            ticker="AZNOULA",
            claim_key="close_fils",
            value=140,
            unit="FILS",
            source_family="boursa_main",
            source_role="REGULATOR_OR_EXCHANGE",
            legal_access=False,
            semantic_complete=False,
        )
        result = aggregate_claim(
            observations=[row],
            policy=close_policy(),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(
            result["excluded"][0]["reason"], "ACCESS_NOT_LEGAL_OR_AUTHORIZED"
        )

    def test_locked_investing_pro_value_is_not_interpreted_as_zero(self) -> None:
        policy = ClaimPolicy(
            claim_key="investingpro_fair_value_fils",
            kind="NUMBER",
            unit="FILS",
            allowed_roles=("LICENSED_MARKET_DATA",),
            minimum_independent_families=1,
        )
        row = observation(
            observation_id="investingpro-locked",
            security_code="ALIMTIAZ",
            ticker="ALIMTIAZ",
            claim_key="investingpro_fair_value_fils",
            value=0,
            unit="FILS",
            source_family="investingpro",
            source_role="LICENSED_MARKET_DATA",
            session_date=None,
            value_unlocked=False,
        )
        inference = ProposedInference(
            claim_key="investingpro_fair_value_fils",
            proposed_value=70,
            unit="FILS",
            confidence="LOW",
            method="DOMAIN_PRIOR_ONLY",
            assumptions=("No authenticated InvestingPro value was available",),
            supported_by_claims=("close_fils",),
        )
        result = aggregate_claim(
            observations=[row],
            policy=policy,
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            inference=inference,
        )
        self.assertEqual(result["status"], "INFERRED_ONLY")
        self.assertFalse(result["fact_usable"])
        self.assertFalse(result["inference"]["may_overwrite_fact"])
        self.assertEqual(result["excluded"][0]["reason"], "VALUE_LOCKED_OR_MASKED")

    def test_drive_archive_is_not_allowed_for_live_close(self) -> None:
        row = observation(
            observation_id="drive-cached-profile",
            security_code="ALIMTIAZ",
            ticker="ALIMTIAZ",
            claim_key="close_fils",
            value=70,
            unit="FILS",
            source_family="google_drive",
            source_role="DRIVE_ARCHIVE",
        )
        policy = ClaimPolicy(
            claim_key="close_fils",
            kind="NUMBER",
            unit="FILS",
            allowed_roles=("DRIVE_ARCHIVE", "SECONDARY_MARKET_DATA"),
            minimum_independent_families=2,
            requires_session_date=True,
            target_session_date="2026-09-03",
            archive_allowed=False,
        )
        result = aggregate_claim(
            observations=[row],
            policy=policy,
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(
            result["excluded"][0]["reason"], "ARCHIVE_NOT_ALLOWED_FOR_THIS_CLAIM"
        )

    def test_inference_never_overwrites_a_resolved_fact(self) -> None:
        rows = [
            observation(
                observation_id="investing-cattl-close",
                security_code="CATTL",
                ticker="CATTL",
                claim_key="close_fils",
                value=176,
                unit="FILS",
                source_family="investing",
                source_role="SECONDARY_MARKET_DATA",
            ),
            observation(
                observation_id="market-cattl-close",
                security_code="CATTL",
                ticker="CATTL",
                claim_key="close_fils",
                value=176,
                unit="FILS",
                source_family="zonebourse",
                source_role="SECONDARY_MARKET_DATA",
            ),
        ]
        inference = ProposedInference(
            claim_key="close_fils",
            proposed_value=180,
            unit="FILS",
            confidence="MEDIUM",
            method="HEURISTIC_ESTIMATE",
            assumptions=("Secondary quote may be stale",),
            supported_by_claims=("close_fils",),
        )
        result = aggregate_claim(
            observations=rows,
            policy=close_policy(),
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
            inference=inference,
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["resolved"]["value"], 176)
        self.assertTrue(result["inference"]["fact_precedence"])
        self.assertFalse(result["inference"]["may_overwrite_fact"])

    def test_security_bundle_declares_in_memory_only_and_no_execution(self) -> None:
        rows = [
            observation(
                observation_id="investing-alimtiaz-close",
                security_code="ALIMTIAZ",
                ticker="ALIMTIAZ",
                claim_key="close_fils",
                value=75.3,
                unit="FILS",
                source_family="investing",
                source_role="SECONDARY_MARKET_DATA",
            ),
            observation(
                observation_id="aletihad-alimtiaz-close",
                security_code="ALIMTIAZ",
                ticker="ALIMTIAZ",
                claim_key="close_fils",
                value=75.3,
                unit="FILS",
                source_family="aletihad",
                source_role="SECONDARY_MARKET_DATA",
            ),
        ]
        result = aggregate_security_claims(
            security_code="ALIMTIAZ",
            ticker="ALIMTIAZ",
            observations=rows,
            policies=[close_policy()],
            decision_at=DECISION_AT,
            capture_mode="HISTORICAL_POINT_IN_TIME",
        )
        self.assertEqual(result["storage_mode"], "IN_MEMORY_ONLY")
        self.assertFalse(result["claim_boundaries"]["local_persistence"])
        self.assertFalse(result["claim_boundaries"]["drive_persistence"])
        self.assertFalse(result["claim_boundaries"]["silent_gap_filling"])
        self.assertFalse(result["claim_boundaries"]["execution"])


if __name__ == "__main__":
    unittest.main()
