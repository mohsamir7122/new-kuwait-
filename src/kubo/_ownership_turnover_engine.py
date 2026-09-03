from __future__ import annotations

import math
from typing import Any, Iterable

from .events import FACT_ROLES
from ._ownership_turnover_models import (
    CAPTURE_MODES, HOLDER_ROLES, MARKET_PHASES, METHOD_ID, OWNERSHIP_EVENT_TYPES,
    RANK_ORDER, SOURCE_ROLES, THRESHOLDS,
    CapitalStructure, HistoricalBar, OwnershipEvent, SessionSnapshot,
)
from ._ownership_turnover_metrics import (
    _canonical_events, _continuation_state, _daily_returns, _directional_state,
    _median_positive, _ownership_state, _risk_label, _window,
)
from .strict import parse_aware, parse_iso_date, require_sha256


def analyze_ownership_turnover(
    *,
    security_code: str,
    ticker: str,
    decision_at: str,
    capture_mode: str,
    capital_structure: CapitalStructure,
    ownership_events: Iterable[OwnershipEvent],
    historical_bars: Iterable[HistoricalBar],
    session_snapshot: SessionSnapshot | None = None,
) -> dict[str, Any]:
    if capture_mode not in CAPTURE_MODES:
        raise ValueError("invalid capture_mode")
    cutoff = parse_aware(decision_at, "decision_at")
    code = str(security_code).strip()
    ticker_text = str(ticker).strip().upper()
    if not code or not ticker_text:
        raise ValueError("security_code and ticker are required")
    if capital_structure.security_code != code:
        raise ValueError("capital structure security_code mismatch")
    if capital_structure.issued_shares <= 0:
        raise ValueError("capital structure issued_shares must be positive")
    if (
        capital_structure.free_float_shares is not None
        and (
            capital_structure.free_float_shares <= 0
            or capital_structure.free_float_shares > capital_structure.issued_shares
        )
    ):
        raise ValueError("capital structure free_float_shares is invalid")
    if not capital_structure.evidence_hashes:
        raise ValueError("capital structure evidence_hashes are required")
    for evidence_hash in capital_structure.evidence_hashes:
        require_sha256(evidence_hash, "capital_structure.evidence_hash")
    if parse_aware(capital_structure.as_of, "capital_structure.as_of") > cutoff:
        raise ValueError("capital structure as_of occurs after decision_at")
    if parse_aware(
        capital_structure.first_available_at, "capital_structure.first_available_at"
    ) > cutoff:
        raise ValueError("capital structure was not available at decision_at")
    capital_available = parse_aware(
        capital_structure.first_available_at, "capital_structure.first_available_at"
    )
    capital_captured = parse_aware(
        capital_structure.captured_at, "capital_structure.captured_at"
    )
    if capital_captured < capital_available:
        raise ValueError("capital structure captured_at precedes first_available_at")
    if capture_mode == "PROSPECTIVE" and capital_captured > cutoff:
        raise ValueError("prospective capital structure captured after decision_at")

    bars = sorted(
        list(historical_bars),
        key=lambda item: parse_iso_date(item.session_date, "session_date"),
    )
    if len(bars) < 5:
        raise ValueError("at least five historical bars are required")
    if any(item.security_code != code for item in bars):
        raise ValueError("historical bar security_code mismatch")
    for item in bars:
        session_day = parse_iso_date(item.session_date, "historical.session_date")
        available_at = parse_aware(item.available_at, "historical.available_at")
        captured_at = parse_aware(item.captured_at, "historical.captured_at")
        if item.close_fils <= 0 or item.volume < 0:
            raise ValueError("historical bar price or volume is invalid")
        if item.volume == 0 and item.turnover_kwd not in (None, 0):
            raise ValueError("zero-volume historical bar has positive turnover")
        if item.volume > 0 and item.turnover_kwd == 0:
            raise ValueError("positive-volume historical bar has zero turnover")
        if item.turnover_kwd is not None and item.turnover_kwd < 0:
            raise ValueError("historical turnover cannot be negative")
        if available_at.date() < session_day:
            raise ValueError("historical bar cannot be available before its session")
        if captured_at < available_at:
            raise ValueError("historical captured_at precedes available_at")
        require_sha256(item.evidence_hash, "historical.evidence_hash")
    dates = [item.session_date for item in bars]
    if len(dates) != len(set(dates)):
        raise ValueError("historical session dates must be unique")
    if any(parse_aware(item.available_at, "available_at") > cutoff for item in bars):
        raise ValueError("historical bar was not available at decision_at")
    if capture_mode == "PROSPECTIVE" and any(
        parse_aware(item.captured_at, "captured_at") > cutoff for item in bars
    ):
        raise ValueError("prospective historical bar captured after decision_at")

    if session_snapshot is not None:
        if session_snapshot.security_code != code:
            raise ValueError("session snapshot security_code mismatch")
        if session_snapshot.market_phase not in MARKET_PHASES:
            raise ValueError("invalid market_phase for traded-session snapshot")
        if (
            min(
                session_snapshot.previous_close_fils,
                session_snapshot.open_fils,
                session_snapshot.high_fils,
                session_snapshot.low_fils,
                session_snapshot.last_fils,
            )
            <= 0
            or session_snapshot.volume < 0
            or session_snapshot.turnover_kwd < 0
        ):
            raise ValueError("snapshot price, volume, or turnover is invalid")
        if (
            session_snapshot.low_fils > session_snapshot.high_fils
            or not session_snapshot.low_fils
            <= session_snapshot.open_fils
            <= session_snapshot.high_fils
            or not session_snapshot.low_fils
            <= session_snapshot.last_fils
            <= session_snapshot.high_fils
        ):
            raise ValueError("snapshot OHLC range is inconsistent")
        if (session_snapshot.volume == 0) != (session_snapshot.turnover_kwd == 0):
            raise ValueError("snapshot volume and turnover must be zero together")
        if (
            session_snapshot.trade_count is not None
            and (
                session_snapshot.trade_count < 0
                or (session_snapshot.volume > 0 and session_snapshot.trade_count == 0)
                or (session_snapshot.volume == 0 and session_snapshot.trade_count > 0)
            )
        ):
            raise ValueError("snapshot trade_count is inconsistent with volume")
        if (
            session_snapshot.market_total_volume is not None
            and session_snapshot.volume > session_snapshot.market_total_volume
        ):
            raise ValueError("security volume exceeds market total volume")
        if (
            session_snapshot.market_total_turnover_kwd is not None
            and session_snapshot.turnover_kwd
            > session_snapshot.market_total_turnover_kwd
        ):
            raise ValueError("security turnover exceeds market total turnover")
        if session_snapshot.volume > 0:
            derived_vwap = (
                session_snapshot.turnover_kwd * 1000.0 / session_snapshot.volume
            )
            vwap_tolerance = max(0.001, session_snapshot.high_fils * 0.01)
            if (
                derived_vwap < session_snapshot.low_fils - vwap_tolerance
                or derived_vwap > session_snapshot.high_fils + vwap_tolerance
            ):
                raise ValueError("derived VWAP lies outside the session range")
        require_sha256(session_snapshot.evidence_hash, "snapshot.evidence_hash")
        snapshot_date = parse_iso_date(session_snapshot.session_date, "session_date")
        snapshot_available = parse_aware(
            session_snapshot.available_at, "snapshot.available_at"
        )
        snapshot_captured = parse_aware(
            session_snapshot.captured_at, "snapshot.captured_at"
        )
        if snapshot_available.date() < snapshot_date:
            raise ValueError("session snapshot cannot be available before its session")
        if snapshot_captured < snapshot_available:
            raise ValueError("snapshot captured_at precedes available_at")
        if any(
            parse_iso_date(item.session_date, "session_date") >= snapshot_date
            for item in bars
        ):
            raise ValueError("historical bars must precede the session snapshot")
        if parse_aware(session_snapshot.available_at, "available_at") > cutoff:
            raise ValueError("session snapshot was not available at decision_at")
        if capture_mode == "PROSPECTIVE" and parse_aware(
            session_snapshot.captured_at, "captured_at"
        ) > cutoff:
            raise ValueError("prospective session snapshot captured after decision_at")

    event_rows = list(ownership_events)
    if any(item.security_code != code for item in event_rows):
        raise ValueError("ownership event security_code mismatch")
    for item in event_rows:
        if item.event_type not in OWNERSHIP_EVENT_TYPES:
            raise ValueError("invalid ownership event_type")
        if item.source_role not in SOURCE_ROLES:
            raise ValueError("invalid ownership source_role")
        if item.holder_role not in HOLDER_ROLES:
            raise ValueError("invalid holder_role")
        published_at = parse_aware(item.published_at, "ownership.published_at")
        available_at = parse_aware(
            item.first_available_at, "ownership.first_available_at"
        )
        captured_at = parse_aware(item.captured_at, "ownership.captured_at")
        if available_at < published_at or captured_at < available_at:
            raise ValueError("ownership timestamp ordering is invalid")
        require_sha256(item.evidence_hash, "ownership.evidence_hash")
        if (
            item.event_type == "BENEFICIAL_OWNERSHIP_CHANGE"
            and (
                item.holder_id is None
                or item.previous_pct is None
                or item.current_pct is None
                or abs(item.current_pct - item.previous_pct) < 1e-12
            )
        ):
            raise ValueError("beneficial ownership change payload is invalid")
    if any(
        item.event_type in {"AGREED_TRADE", "BLOCK_TRADE"}
        and (item.shares or 0) > capital_structure.issued_shares
        for item in event_rows
    ):
        raise ValueError("single block/agreed trade exceeds issued shares")
    if capture_mode == "PROSPECTIVE" and any(
        parse_aware(item.first_available_at, "first_available_at") <= cutoff
        and parse_aware(item.captured_at, "captured_at") > cutoff
        for item in event_rows
    ):
        raise ValueError("prospective ownership event captured after decision_at")
    available_event_rows = [
        item
        for item in event_rows
        if parse_aware(item.first_available_at, "first_available_at") <= cutoff
    ]
    canonical, conflicts = _canonical_events(event_rows, decision_at=cutoff)
    official_180 = [
        item for item in _window(canonical, cutoff, 180) if item.source_role in FACT_ROLES
    ]
    context_180 = [
        item
        for item in _window(canonical, cutoff, 180)
        if item.source_role not in FACT_ROLES
    ]

    median_volume_20 = _median_positive(item.volume for item in bars[-20:])
    relative_volume_20d = (
        session_snapshot.volume / median_volume_20
        if session_snapshot is not None
        and median_volume_20 is not None
        and median_volume_20 > 0
        else None
    )
    combined_volumes = [item.volume for item in bars]
    if session_snapshot is not None:
        combined_volumes.append(session_snapshot.volume)
    trailing_5_volume = sum(combined_volumes[-5:])
    issued_turnover_5d_ratio = trailing_5_volume / capital_structure.issued_shares
    free_float_turnover_5d_ratio = (
        trailing_5_volume / capital_structure.free_float_shares
        if capital_structure.free_float_shares
        else None
    )
    session_issued_turnover_ratio = (
        session_snapshot.volume / capital_structure.issued_shares
        if session_snapshot is not None
        else None
    )
    session_free_float_turnover_ratio = (
        session_snapshot.volume / capital_structure.free_float_shares
        if session_snapshot is not None and capital_structure.free_float_shares
        else None
    )
    returns = _daily_returns(bars[-61:])
    sudden_move_count = sum(
        abs(value) >= THRESHOLDS["sudden_move_return"] for value in returns
    )
    realized_rms_return = (
        math.sqrt(sum(value * value for value in returns) / len(returns))
        if returns
        else None
    )
    movement_risk = _risk_label(
        rvol=relative_volume_20d,
        free_float_turnover_ratio=session_free_float_turnover_ratio,
        issued_turnover_5d_ratio=issued_turnover_5d_ratio,
        sudden_move_count=sudden_move_count,
    )
    ownership_state, ownership_reasons, ownership_metrics = _ownership_state(
        official_180,
        issued_shares=capital_structure.issued_shares,
        free_float_shares=capital_structure.free_float_shares,
    )
    activity_confirmed = bool(
        (
            relative_volume_20d is not None
            and relative_volume_20d >= THRESHOLDS["relative_volume_high"]
        )
        or (
            session_issued_turnover_ratio is not None
            and session_issued_turnover_ratio
            >= THRESHOLDS["session_issued_turnover_confirmation"]
        )
        or (
            session_free_float_turnover_ratio is not None
            and session_free_float_turnover_ratio
            >= THRESHOLDS["session_free_float_turnover_high"]
        )
    )
    activity_extreme = bool(
        (
            relative_volume_20d is not None
            and relative_volume_20d
            >= THRESHOLDS["relative_volume_activity_extreme"]
        )
        or (
            session_free_float_turnover_ratio is not None
            and session_free_float_turnover_ratio
            >= THRESHOLDS["session_free_float_turnover_extreme"]
        )
    )
    directional_state, directional_reasons, directional_metrics = _directional_state(
        session_snapshot, activity_confirmed=activity_confirmed
    )
    continuation_state, continuation_reasons = _continuation_state(
        directional_state,
        directional_metrics,
        activity_extreme=activity_extreme,
    )

    reason_codes = list(
        ownership_reasons + directional_reasons + continuation_reasons
    )
    if (
        relative_volume_20d is not None
        and relative_volume_20d >= THRESHOLDS["relative_volume_extreme"]
    ):
        reason_codes.append("EXTREME_RELATIVE_VOLUME_GE_10X")
    elif (
        relative_volume_20d is not None
        and relative_volume_20d >= THRESHOLDS["relative_volume_high"]
    ):
        reason_codes.append("HIGH_RELATIVE_VOLUME_GE_3X")
    if (
        session_free_float_turnover_ratio is not None
        and session_free_float_turnover_ratio
        >= THRESHOLDS["session_free_float_turnover_full_rotation"]
    ):
        reason_codes.append("FULL_FREE_FLOAT_ROTATION_GE_100PCT")
    elif (
        session_free_float_turnover_ratio is not None
        and session_free_float_turnover_ratio
        >= THRESHOLDS["session_free_float_turnover_extreme"]
    ):
        reason_codes.append("EXTREME_FREE_FLOAT_ROTATION_GE_50PCT")
    if (
        issued_turnover_5d_ratio
        >= THRESHOLDS["cumulative_5d_issued_turnover_high"]
    ):
        reason_codes.append("CUMULATIVE_5D_TURNOVER_GE_10PCT_ISSUED")
    if context_180 and not official_180:
        reason_codes.append("CONTEXT_ONLY_OWNERSHIP_LEADS")
    if capital_structure.free_float_shares is None:
        reason_codes.append("FREE_FLOAT_MISSING")
    if conflicts:
        reason_codes.append("CONFLICTING_CANONICAL_EVENT_PAYLOAD")
    snapshot_finality = (
        "NOT_OBSERVED"
        if session_snapshot is None
        else "FINAL_SESSION"
        if session_snapshot.market_phase == "CLOSED"
        else "PROVISIONAL_INTRADAY"
    )
    if snapshot_finality == "PROVISIONAL_INTRADAY":
        reason_codes.append("INTRADAY_SNAPSHOT_PROVISIONAL")

    if conflicts:
        research_status = "HUMAN_REVIEW_REQUIRED"
    elif (
        ownership_state == "CONFIRMED_CONTROL_RELEVANT_EVENT"
        and directional_state in {"POSITIVE_CONFIRMED", "NEGATIVE_CONFIRMED"}
    ):
        research_status = "EVENT_CONFIRMED"
    elif ownership_state == "CONFIRMED_CONTROL_RELEVANT_EVENT":
        research_status = "HIGH_PRIORITY_WATCH"
    elif (
        movement_risk == "VERY_HIGH"
        and (
            ownership_state
            in {"CONFIRMED_MATERIAL_OWNERSHIP_EVENT", "OFFICIAL_EVENT_OBSERVED"}
            or bool(context_180)
        )
    ):
        research_status = "DISCOVERY_ALERT"
    elif ownership_state == "CONFIRMED_MATERIAL_OWNERSHIP_EVENT":
        research_status = "HIGH_PRIORITY_WATCH"
    elif movement_risk in {"VERY_HIGH", "HIGH"}:
        research_status = "ANOMALY_WATCH"
    else:
        research_status = "ABSTAIN"

    timeline_discontinuities = ownership_metrics[
        "ownership_timeline_discontinuity_count_180d"
    ]
    evidence_status = (
        "CONFLICT"
        if conflicts
        else "PARTIAL"
        if capital_structure.free_float_shares is None
        or (bool(context_180) and not bool(official_180))
        or timeline_discontinuities > 0
        else "COMPLETE"
    )
    metrics = {
        **ownership_metrics,
        **directional_metrics,
        "median_volume_20d": median_volume_20,
        "relative_volume_20d": relative_volume_20d,
        "session_turnover_ratio_issued": session_issued_turnover_ratio,
        "session_turnover_ratio_free_float": session_free_float_turnover_ratio,
        "cumulative_turnover_5d_ratio_issued": issued_turnover_5d_ratio,
        "cumulative_turnover_5d_ratio_free_float": free_float_turnover_5d_ratio,
        "realized_rms_daily_return_60d": realized_rms_return,
        "sudden_move_count_60d": sudden_move_count,
        "context_only_event_count_180d": len(context_180),
    }
    evidence_hashes = sorted(
        set(capital_structure.evidence_hashes)
        | {item.evidence_hash for item in bars}
        | {item.evidence_hash for item in available_event_rows}
        | ({session_snapshot.evidence_hash} if session_snapshot is not None else set())
    )
    return {
        "schema_version": "1.0",
        "method_id": METHOD_ID,
        "security_code": code,
        "ticker": ticker_text,
        "decision_at": cutoff.isoformat(),
        "capture_mode": capture_mode,
        "operational_status": "PASS",
        "evidence_status": evidence_status,
        "research_status": research_status,
        "trade_eligibility": "BLOCKED",
        "components": {
            "movement_risk": movement_risk,
            "ownership_event": ownership_state,
            "directional_confirmation": directional_state,
            "continuation_structure": continuation_state,
            "snapshot_finality": snapshot_finality,
        },
        "input_state": {
            "capital_structure": capital_structure.to_dict(),
            "historical_session_count": len(bars),
            "available_event_count": len(available_event_rows),
            "canonical_event_count": len(canonical),
            "session_snapshot": None
            if session_snapshot is None
            else {
                "session_date": session_snapshot.session_date,
                "market_phase": session_snapshot.market_phase,
                "available_at": session_snapshot.available_at,
                "captured_at": session_snapshot.captured_at,
            },
        },
        "metrics": metrics,
        "reason_codes": sorted(set(reason_codes)),
        "conflicting_canonical_event_ids": conflicts,
        "evidence_hashes": evidence_hashes,
        "methodology": {
            "thresholds": dict(sorted(THRESHOLDS.items())),
            "ratio_unit": "DECIMAL_FRACTION",
            "ownership_change_unit": "PERCENTAGE_POINTS",
            "ranking_scope": "INVESTIGATION_PRIORITY_ONLY",
        },
        "claim_boundaries": {
            "live_collection": False,
            "probability": False,
            "recommendation": False,
            "entry_price": False,
            "order_execution": False,
            "output_class": "EVENT_AND_MARKET_ANOMALY_RADAR_ONLY",
        },
    }


def scan_ownership_turnover_universe(
    cases: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case_{index} must be an object")
        result = analyze_ownership_turnover(**case)
        security_code = result["security_code"]
        if security_code in seen:
            raise ValueError(f"duplicate security_code in universe: {security_code}")
        seen.add(security_code)
        results.append(result)
    results.sort(
        key=lambda item: (
            RANK_ORDER[item["research_status"]],
            0 if item["components"]["movement_risk"] == "VERY_HIGH" else 1,
            item["security_code"],
        )
    )
    for rank, result in enumerate(results, start=1):
        result["investigation_rank"] = rank
    return results
