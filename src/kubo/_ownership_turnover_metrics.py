from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any, Iterable

from ._ownership_turnover_models import HistoricalBar, OwnershipEvent, SessionSnapshot, THRESHOLDS
from .strict import parse_aware


def _event_signature(event: OwnershipEvent) -> tuple[Any, ...]:
    return (
        event.security_code,
        event.event_type,
        event.holder_id,
        event.holder_role,
        event.buyer_id,
        event.seller_id,
        event.previous_pct,
        event.current_pct,
        event.shares,
        event.transaction_price_fils,
        event.occurred_at,
    )


def _canonical_events(
    events: Iterable[OwnershipEvent], *, decision_at: datetime
) -> tuple[list[OwnershipEvent], list[str]]:
    by_event_id: set[str] = set()
    groups: dict[str, list[OwnershipEvent]] = {}
    for event in events:
        if event.event_id in by_event_id:
            raise ValueError(f"duplicate ownership event_id: {event.event_id}")
        by_event_id.add(event.event_id)
        if parse_aware(event.first_available_at, "first_available_at") <= decision_at:
            groups.setdefault(event.canonical_event_id, []).append(event)
    canonical: list[OwnershipEvent] = []
    conflicts: list[str] = []
    role_rank = {
        "REGULATOR_OR_EXCHANGE": 0,
        "OFFICIAL_FILING": 1,
        "ISSUER_PRIMARY": 2,
        "FINANCIAL_CONTEXT": 3,
        "NEWS_CONTEXT": 4,
        "FORUM": 5,
        "TELEGRAM": 6,
        "SOCIAL": 7,
    }
    for canonical_id, group in groups.items():
        if len({_event_signature(item) for item in group}) > 1:
            conflicts.append(canonical_id)
            continue
        group.sort(
            key=lambda item: (
                role_rank.get(item.source_role, 99),
                parse_aware(item.first_available_at, "first_available_at"),
                item.event_id,
            )
        )
        canonical.append(group[0])
    canonical.sort(
        key=lambda item: (
            parse_aware(item.first_available_at, "first_available_at"),
            item.canonical_event_id,
        )
    )
    return canonical, sorted(conflicts)


def _window(
    events: Iterable[OwnershipEvent], cutoff: datetime, days: int
) -> list[OwnershipEvent]:
    start = cutoff - timedelta(days=days)
    return [
        item
        for item in events
        if start <= parse_aware(item.first_available_at, "first_available_at") <= cutoff
    ]


def _median_positive(values: Iterable[int]) -> float | None:
    positive = [float(value) for value in values if value > 0]
    return median(positive) if positive else None


def _daily_returns(bars: list[HistoricalBar]) -> list[float]:
    closes = [item.close_fils for item in bars]
    return [current / previous - 1.0 for previous, current in zip(closes, closes[1:])]


def _risk_label(
    *,
    rvol: float | None,
    free_float_turnover_ratio: float | None,
    issued_turnover_5d_ratio: float,
    sudden_move_count: int,
) -> str:
    if (
        (rvol is not None and rvol >= THRESHOLDS["relative_volume_extreme"])
        or (
            free_float_turnover_ratio is not None
            and free_float_turnover_ratio
            >= THRESHOLDS["session_free_float_turnover_extreme"]
        )
        or issued_turnover_5d_ratio
        >= THRESHOLDS["cumulative_5d_issued_turnover_extreme"]
        or sudden_move_count >= THRESHOLDS["sudden_move_count_extreme"]
    ):
        return "VERY_HIGH"
    if (
        (rvol is not None and rvol >= THRESHOLDS["relative_volume_high"])
        or (
            free_float_turnover_ratio is not None
            and free_float_turnover_ratio
            >= THRESHOLDS["session_free_float_turnover_high"]
        )
        or issued_turnover_5d_ratio
        >= THRESHOLDS["cumulative_5d_issued_turnover_high"]
        or sudden_move_count >= THRESHOLDS["sudden_move_count_high"]
    ):
        return "HIGH"
    return "MODERATE"


def _timeline_discontinuity_count(events: Iterable[OwnershipEvent]) -> int:
    by_holder: dict[str, list[OwnershipEvent]] = {}
    for item in events:
        if (
            item.event_type == "BENEFICIAL_OWNERSHIP_CHANGE"
            and item.holder_id is not None
            and item.previous_pct is not None
            and item.current_pct is not None
        ):
            by_holder.setdefault(item.holder_id, []).append(item)
    count = 0
    tolerance = THRESHOLDS["timeline_continuity_tolerance_pp"]
    for rows in by_holder.values():
        rows.sort(key=lambda item: parse_aware(item.occurred_at, "occurred_at"))
        for prior, current in zip(rows, rows[1:]):
            assert prior.current_pct is not None and current.previous_pct is not None
            if abs(prior.current_pct - current.previous_pct) > tolerance:
                count += 1
    return count


def _ownership_state(
    official_events: list[OwnershipEvent],
    *,
    issued_shares: int,
    free_float_shares: int | None,
) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    changes = [
        item
        for item in official_events
        if item.event_type == "BENEFICIAL_OWNERSHIP_CHANGE"
        and item.ownership_delta_pct is not None
    ]
    net_change = sum(item.ownership_delta_pct or 0.0 for item in changes)
    gross_change = sum(abs(item.ownership_delta_pct or 0.0) for item in changes)
    major_holder_reduction = sum(
        -(item.ownership_delta_pct or 0.0)
        for item in changes
        if item.holder_role == "MAJOR_HOLDER"
        and (item.ownership_delta_pct or 0.0) < 0
    )
    exits = sum(
        1
        for item in changes
        if item.holder_role == "MAJOR_HOLDER"
        and item.previous_pct is not None
        and item.previous_pct >= 5
        and item.current_pct == 0
    )
    block_events = [
        item
        for item in official_events
        if item.event_type in {"AGREED_TRADE", "BLOCK_TRADE"}
    ]
    block_shares = sum(item.shares or 0 for item in block_events)
    block_clusters: dict[str, int] = {}
    for item in block_events:
        cluster_day = parse_aware(item.occurred_at, "occurred_at").date().isoformat()
        block_clusters[cluster_day] = block_clusters.get(cluster_day, 0) + (item.shares or 0)
    max_block_cluster_shares = max(block_clusters.values(), default=0)
    block_ratio_issued = (
        max_block_cluster_shares / issued_shares if max_block_cluster_shares else 0.0
    )
    block_ratio_free_float = (
        max_block_cluster_shares / free_float_shares
        if max_block_cluster_shares and free_float_shares
        else None
    )
    insider_supply_events = sum(
        1
        for item in official_events
        if item.event_type in {"INSIDER_TRADE", "AFFILIATE_TRADE"}
        and (item.shares or 0) > 0
        and item.seller_id is not None
        and (item.holder_id is None or item.seller_id == item.holder_id)
    )
    timeline_discontinuities = _timeline_discontinuity_count(changes)
    if block_ratio_issued >= THRESHOLDS["block_issued_control_relevant"]:
        reasons.append("CONTROL_RELEVANT_BLOCK_GE_20PCT_ISSUED")
    elif block_ratio_issued >= THRESHOLDS["block_issued_material"]:
        reasons.append("MATERIAL_BLOCK_GE_10PCT_ISSUED")
    if (
        block_ratio_free_float is not None
        and block_ratio_free_float >= THRESHOLDS["block_free_float_material"]
    ):
        reasons.append("BLOCK_GE_40PCT_FREE_FLOAT")
    if exits:
        reasons.append("MAJOR_HOLDER_EXIT")
    if major_holder_reduction >= THRESHOLDS["major_holder_reduction_material_pp"]:
        reasons.append("CUMULATIVE_MAJOR_HOLDER_REDUCTION_GE_5PP")
    if insider_supply_events >= 2:
        reasons.append("INSIDER_OR_AFFILIATE_SUPPLY_CLUSTER")
    if timeline_discontinuities:
        reasons.append("OWNERSHIP_TIMELINE_DISCONTINUITY")
    if block_ratio_issued >= THRESHOLDS["block_issued_material"] or exits:
        state = "CONFIRMED_CONTROL_RELEVANT_EVENT"
    elif (
        major_holder_reduction
        >= THRESHOLDS["major_holder_reduction_material_pp"]
        or gross_change >= THRESHOLDS["major_holder_reduction_material_pp"]
        or insider_supply_events >= 2
    ):
        state = "CONFIRMED_MATERIAL_OWNERSHIP_EVENT"
    elif official_events:
        state = "OFFICIAL_EVENT_OBSERVED"
    else:
        state = "NONE_OBSERVED"
    metrics = {
        "official_ownership_event_count_180d": len(official_events),
        "ownership_net_change_percentage_points_180d": net_change,
        "ownership_gross_change_percentage_points_180d": gross_change,
        "major_holder_reduction_percentage_points_180d": major_holder_reduction,
        "major_holder_exit_count_180d": exits,
        "ownership_timeline_discontinuity_count_180d": timeline_discontinuities,
        "insider_affiliate_supply_event_count_180d": insider_supply_events,
        "block_shares_180d": block_shares,
        "max_block_cluster_shares_180d": max_block_cluster_shares,
        "max_block_cluster_ratio_issued_shares_180d": block_ratio_issued,
        "max_block_cluster_ratio_free_float_180d": block_ratio_free_float,
    }
    return state, reasons, metrics


def _directional_state(
    snapshot: SessionSnapshot | None,
    *,
    activity_confirmed: bool,
) -> tuple[str, list[str], dict[str, Any]]:
    if snapshot is None:
        return "NOT_OBSERVED", [], {
            "opening_gap_return": None,
            "session_return": None,
            "close_location_ratio": None,
            "high_to_last_giveback_ratio": None,
            "vwap_fils": None,
            "last_vs_vwap_return": None,
            "relative_strength_vs_market": None,
            "relative_strength_vs_sector": None,
        }
    opening_gap = snapshot.open_fils / snapshot.previous_close_fils - 1.0
    session_return = snapshot.last_fils / snapshot.previous_close_fils - 1.0
    price_range = snapshot.high_fils - snapshot.low_fils
    close_location = (
        (snapshot.last_fils - snapshot.low_fils) / price_range
        if price_range > 0
        else 0.5
    )
    giveback = (
        (snapshot.high_fils - snapshot.last_fils) / snapshot.high_fils
        if snapshot.high_fils > 0
        else 0.0
    )
    vwap = (
        snapshot.turnover_kwd * 1000.0 / snapshot.volume
        if snapshot.volume > 0
        else None
    )
    last_vs_vwap = snapshot.last_fils / vwap - 1.0 if vwap else None
    relative_market = (
        session_return - snapshot.market_return_fraction
        if snapshot.market_return_fraction is not None
        else None
    )
    relative_sector = (
        session_return - snapshot.sector_return_fraction
        if snapshot.sector_return_fraction is not None
        else None
    )
    reasons: list[str] = []
    positive_support = close_location >= THRESHOLDS["close_location_positive_support"] or (
        relative_market is not None
        and relative_market >= THRESHOLDS["relative_strength_material"]
        and (
            last_vs_vwap is None
            or last_vs_vwap >= -THRESHOLDS["vwap_support_tolerance"]
        )
    )
    negative_support = close_location <= THRESHOLDS["close_location_negative_support"] or (
        relative_market is not None
        and relative_market <= -THRESHOLDS["relative_strength_material"]
        and (
            last_vs_vwap is None
            or last_vs_vwap <= THRESHOLDS["vwap_support_tolerance"]
        )
    )
    if (
        session_return >= THRESHOLDS["directional_return_confirmation"]
        and activity_confirmed
        and positive_support
    ):
        state = "POSITIVE_CONFIRMED"
        reasons.append("POSITIVE_PRICE_VOLUME_CONFIRMATION")
    elif (
        session_return <= -THRESHOLDS["directional_return_confirmation"]
        and activity_confirmed
        and negative_support
    ):
        state = "NEGATIVE_CONFIRMED"
        reasons.append("NEGATIVE_PRICE_VOLUME_CONFIRMATION")
    elif session_return >= THRESHOLDS["tentative_directional_return"]:
        state = "TENTATIVE_POSITIVE"
    elif session_return <= -THRESHOLDS["tentative_directional_return"]:
        state = "TENTATIVE_NEGATIVE"
    else:
        state = "UNCONFIRMED"
    if abs(opening_gap) >= THRESHOLDS["opening_gap_material"]:
        reasons.append("MATERIAL_OPENING_GAP")
    if (
        relative_market is not None
        and abs(relative_market) >= THRESHOLDS["relative_strength_material"]
    ):
        reasons.append("STOCK_SPECIFIC_RELATIVE_STRENGTH")
    return state, reasons, {
        "opening_gap_return": opening_gap,
        "session_return": session_return,
        "close_location_ratio": close_location,
        "high_to_last_giveback_ratio": giveback,
        "vwap_fils": vwap,
        "last_vs_vwap_return": last_vs_vwap,
        "relative_strength_vs_market": relative_market,
        "relative_strength_vs_sector": relative_sector,
    }


def _continuation_state(
    directional_state: str,
    directional_metrics: dict[str, Any],
    *,
    activity_extreme: bool,
) -> tuple[str, list[str]]:
    if directional_state not in {"POSITIVE_CONFIRMED", "NEGATIVE_CONFIRMED"}:
        return "NOT_APPLICABLE", []
    giveback = directional_metrics["high_to_last_giveback_ratio"]
    close_location = directional_metrics["close_location_ratio"]
    last_vs_vwap = directional_metrics["last_vs_vwap_return"]
    if directional_state == "POSITIVE_CONFIRMED":
        if activity_extreme and (
            (giveback is not None and giveback >= THRESHOLDS["giveback_warning"])
            or (
                close_location is not None
                and close_location < THRESHOLDS["close_location_distribution_warning"]
            )
            or (
                last_vs_vwap is not None
                and last_vs_vwap < -THRESHOLDS["vwap_support_tolerance"]
            )
        ):
            return "ELEVATED_REVERSAL_RISK", [
                "VOLUME_CLIMAX_OR_DISTRIBUTION_RISK"
            ]
        if (
            close_location is not None
            and close_location >= THRESHOLDS["close_location_continuation_healthy"]
            and (last_vs_vwap is None or last_vs_vwap >= 0)
        ):
            return "HEALTHY_CONTINUATION_STRUCTURE", []
        return "MIXED_CONTINUATION_STRUCTURE", []
    if close_location is not None and close_location <= 0.25:
        return "NEGATIVE_CONTINUATION_STRUCTURE", []
    return "MIXED_CONTINUATION_STRUCTURE", []
