from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math
from statistics import median
from typing import Any, Iterable

from .events import FACT_ROLES, SOURCE_ROLES
from .strict import finite_number, parse_aware, parse_iso_date, require_sha256


OWNERSHIP_EVENT_TYPES = frozenset(
    {
        "BENEFICIAL_OWNERSHIP_CHANGE",
        "INSIDER_TRADE",
        "AFFILIATE_TRADE",
        "AGREED_TRADE",
        "BLOCK_TRADE",
        "CONTROL_CHANGE",
        "BOARD_CHANGE",
    }
)
HOLDER_ROLES = frozenset({"MAJOR_HOLDER", "INSIDER", "AFFILIATE", "UNKNOWN"})
MARKET_PHASES = frozenset(
    {
        "PRE_OPEN",
        "OPENING_AUCTION",
        "CONTINUOUS_TRADING",
        "CLOSING_AUCTION",
        "CLOSED",
    }
)
CAPTURE_MODES = frozenset({"PROSPECTIVE", "HISTORICAL_POINT_IN_TIME"})
RANK_ORDER = {
    "EVENT_CONFIRMED": 0,
    "DISCOVERY_ALERT": 1,
    "HIGH_PRIORITY_WATCH": 2,
    "ANOMALY_WATCH": 3,
    "HUMAN_REVIEW_REQUIRED": 4,
    "ABSTAIN": 5,
}


@dataclass(frozen=True)
class CapitalStructure:
    security_code: str
    issued_shares: int
    free_float_shares: int | None
    as_of: str
    evidence_hashes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OwnershipEvent:
    event_id: str
    canonical_event_id: str
    security_code: str
    event_type: str
    source_role: str
    holder_id: str | None
    holder_role: str
    buyer_id: str | None
    seller_id: str | None
    previous_pct: float | None
    current_pct: float | None
    shares: int | None
    transaction_price_fils: float | None
    occurred_at: str
    published_at: str
    first_available_at: str
    captured_at: str
    evidence_hash: str

    @property
    def ownership_delta_pct(self) -> float | None:
        if self.previous_pct is None or self.current_pct is None:
            return None
        return self.current_pct - self.previous_pct

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["ownership_delta_pct"] = self.ownership_delta_pct
        return result


@dataclass(frozen=True)
class HistoricalBar:
    security_code: str
    session_date: str
    close_fils: float
    volume: int
    turnover_kwd: float | None
    available_at: str
    captured_at: str
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionSnapshot:
    security_code: str
    session_date: str
    market_phase: str
    previous_close_fils: float
    open_fils: float
    high_fils: float
    low_fils: float
    last_fils: float
    volume: int
    turnover_kwd: float
    trade_count: int | None
    market_total_volume: int | None
    market_total_turnover_kwd: float | None
    market_return_pct: float | None
    sector_return_pct: float | None
    available_at: str
    captured_at: str
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if parsed < 0 or str(parsed) != str(value).strip():
        raise ValueError(f"{field} must be a non-negative integer")
    return parsed


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value in (None, ""):
        return None
    return finite_number(value, field, minimum=minimum, maximum=maximum)


def _optional_int(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    return _nonnegative_int(value, field)


def capital_structure_from_dict(
    row: dict[str, Any], *, manifest_hashes: frozenset[str], decision_at: str
) -> CapitalStructure:
    security_code = str(row.get("security_code", "")).strip()
    if not security_code:
        raise ValueError("capital_structure.security_code is required")
    issued = _positive_int(row.get("issued_shares"), "capital_structure.issued_shares")
    free_float_value = row.get("free_float_shares")
    free_float = None if free_float_value in (None, "") else _positive_int(
        free_float_value, "capital_structure.free_float_shares"
    )
    if free_float is not None and free_float > issued:
        raise ValueError("free_float_shares cannot exceed issued_shares")
    as_of = parse_aware(row.get("as_of"), "capital_structure.as_of")
    if as_of > parse_aware(decision_at, "decision_at"):
        raise ValueError("capital structure occurs after decision_at")
    hashes_value = row.get("evidence_hashes")
    if not isinstance(hashes_value, list) or not hashes_value:
        raise ValueError("capital_structure.evidence_hashes must be a non-empty list")
    hashes = tuple(
        sorted({require_sha256(value, "capital_structure.evidence_hash") for value in hashes_value})
    )
    if set(hashes) - manifest_hashes:
        raise ValueError("capital structure evidence does not resolve")
    return CapitalStructure(security_code, issued, free_float, as_of.isoformat(), hashes)


def ownership_event_from_dict(
    row: dict[str, Any], *, manifest_hashes: frozenset[str]
) -> OwnershipEvent:
    event_id = str(row.get("event_id", "")).strip()
    canonical_event_id = str(row.get("canonical_event_id", "")).strip()
    security_code = str(row.get("security_code", "")).strip()
    if not event_id or not canonical_event_id or not security_code:
        raise ValueError("ownership event identifiers are required")
    event_type = str(row.get("event_type", "")).upper()
    if event_type not in OWNERSHIP_EVENT_TYPES:
        raise ValueError("invalid ownership event_type")
    source_role = str(row.get("source_role", "")).upper()
    if source_role not in SOURCE_ROLES:
        raise ValueError("invalid ownership source_role")
    holder_role = str(row.get("holder_role", "UNKNOWN")).upper()
    if holder_role not in HOLDER_ROLES:
        raise ValueError("invalid holder_role")
    previous_pct = _optional_number(
        row.get("previous_pct"), "ownership.previous_pct", minimum=0, maximum=100
    )
    current_pct = _optional_number(
        row.get("current_pct"), "ownership.current_pct", minimum=0, maximum=100
    )
    shares = _optional_int(row.get("shares"), "ownership.shares")
    if event_type == "BENEFICIAL_OWNERSHIP_CHANGE":
        if previous_pct is None or current_pct is None:
            raise ValueError("ownership change requires previous_pct and current_pct")
        if not _optional_text(row.get("holder_id")):
            raise ValueError("ownership change requires holder_id")
    if event_type in {"AGREED_TRADE", "BLOCK_TRADE"} and (shares is None or shares <= 0):
        raise ValueError("block/agreed trade requires positive shares")
    transaction_price = _optional_number(
        row.get("transaction_price_fils"),
        "ownership.transaction_price_fils",
        minimum=0.001,
    )
    occurred = parse_aware(row.get("occurred_at"), "ownership.occurred_at")
    published = parse_aware(row.get("published_at"), "ownership.published_at")
    available = parse_aware(row.get("first_available_at"), "ownership.first_available_at")
    captured = parse_aware(row.get("captured_at"), "ownership.captured_at")
    if available < published or captured < available:
        raise ValueError("ownership timestamp ordering is invalid")
    evidence_hash = require_sha256(row.get("evidence_hash"), "ownership.evidence_hash")
    if evidence_hash not in manifest_hashes:
        raise ValueError("ownership evidence does not resolve")
    return OwnershipEvent(
        event_id=event_id,
        canonical_event_id=canonical_event_id,
        security_code=security_code,
        event_type=event_type,
        source_role=source_role,
        holder_id=_optional_text(row.get("holder_id")),
        holder_role=holder_role,
        buyer_id=_optional_text(row.get("buyer_id")),
        seller_id=_optional_text(row.get("seller_id")),
        previous_pct=previous_pct,
        current_pct=current_pct,
        shares=shares,
        transaction_price_fils=transaction_price,
        occurred_at=occurred.isoformat(),
        published_at=published.isoformat(),
        first_available_at=available.isoformat(),
        captured_at=captured.isoformat(),
        evidence_hash=evidence_hash,
    )


def historical_bar_from_dict(
    row: dict[str, Any], *, manifest_hashes: frozenset[str]
) -> HistoricalBar:
    security_code = str(row.get("security_code", "")).strip()
    if not security_code:
        raise ValueError("historical bar security_code is required")
    session = parse_iso_date(row.get("session_date"), "historical.session_date")
    close = finite_number(row.get("close_fils"), "historical.close_fils", minimum=0.001)
    volume = _nonnegative_int(row.get("volume"), "historical.volume")
    turnover = _optional_number(
        row.get("turnover_kwd"), "historical.turnover_kwd", minimum=0
    )
    if volume == 0 and turnover not in (None, 0.0):
        raise ValueError("zero-volume bar cannot have positive turnover")
    if volume > 0 and turnover == 0:
        raise ValueError("positive-volume bar cannot have zero turnover")
    available = parse_aware(row.get("available_at"), "historical.available_at")
    captured = parse_aware(row.get("captured_at"), "historical.captured_at")
    if captured < available:
        raise ValueError("historical captured_at precedes available_at")
    evidence_hash = require_sha256(row.get("evidence_hash"), "historical.evidence_hash")
    if evidence_hash not in manifest_hashes:
        raise ValueError("historical evidence does not resolve")
    return HistoricalBar(
        security_code,
        session.isoformat(),
        close,
        volume,
        turnover,
        available.isoformat(),
        captured.isoformat(),
        evidence_hash,
    )


def session_snapshot_from_dict(
    row: dict[str, Any], *, manifest_hashes: frozenset[str]
) -> SessionSnapshot:
    security_code = str(row.get("security_code", "")).strip()
    if not security_code:
        raise ValueError("session snapshot security_code is required")
    session = parse_iso_date(row.get("session_date"), "snapshot.session_date")
    phase = str(row.get("market_phase", "")).upper()
    if phase not in MARKET_PHASES:
        raise ValueError("invalid market_phase")
    previous_close = finite_number(
        row.get("previous_close_fils"), "snapshot.previous_close_fils", minimum=0.001
    )
    open_fils = finite_number(row.get("open_fils"), "snapshot.open_fils", minimum=0.001)
    high = finite_number(row.get("high_fils"), "snapshot.high_fils", minimum=0.001)
    low = finite_number(row.get("low_fils"), "snapshot.low_fils", minimum=0.001)
    last = finite_number(row.get("last_fils"), "snapshot.last_fils", minimum=0.001)
    if low > high or not low <= open_fils <= high or not low <= last <= high:
        raise ValueError("snapshot OHLC range is inconsistent")
    volume = _nonnegative_int(row.get("volume"), "snapshot.volume")
    turnover = finite_number(row.get("turnover_kwd"), "snapshot.turnover_kwd", minimum=0)
    if (volume == 0) != (turnover == 0):
        raise ValueError("snapshot volume and turnover must be zero together")
    trade_count = _optional_int(row.get("trade_count"), "snapshot.trade_count")
    market_total_volume = _optional_int(
        row.get("market_total_volume"), "snapshot.market_total_volume"
    )
    market_total_turnover = _optional_number(
        row.get("market_total_turnover_kwd"),
        "snapshot.market_total_turnover_kwd",
        minimum=0,
    )
    if market_total_volume is not None and volume > market_total_volume:
        raise ValueError("security volume exceeds market total volume")
    if market_total_turnover is not None and turnover > market_total_turnover:
        raise ValueError("security turnover exceeds market total turnover")
    if volume > 0:
        vwap = turnover * 1000.0 / volume
        tolerance = max(0.001, high * 0.01)
        if vwap < low - tolerance or vwap > high + tolerance:
            raise ValueError("derived VWAP lies outside the session range")
    available = parse_aware(row.get("available_at"), "snapshot.available_at")
    captured = parse_aware(row.get("captured_at"), "snapshot.captured_at")
    if captured < available:
        raise ValueError("snapshot captured_at precedes available_at")
    evidence_hash = require_sha256(row.get("evidence_hash"), "snapshot.evidence_hash")
    if evidence_hash not in manifest_hashes:
        raise ValueError("snapshot evidence does not resolve")
    return SessionSnapshot(
        security_code=security_code,
        session_date=session.isoformat(),
        market_phase=phase,
        previous_close_fils=previous_close,
        open_fils=open_fils,
        high_fils=high,
        low_fils=low,
        last_fils=last,
        volume=volume,
        turnover_kwd=turnover,
        trade_count=trade_count,
        market_total_volume=market_total_volume,
        market_total_turnover_kwd=market_total_turnover,
        market_return_pct=_optional_number(
            row.get("market_return_pct"), "snapshot.market_return_pct"
        ),
        sector_return_pct=_optional_number(
            row.get("sector_return_pct"), "snapshot.sector_return_pct"
        ),
        available_at=available.isoformat(),
        captured_at=captured.isoformat(),
        evidence_hash=evidence_hash,
    )


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
        signatures = {_event_signature(item) for item in group}
        if len(signatures) > 1:
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


def _window(events: Iterable[OwnershipEvent], cutoff: datetime, days: int) -> list[OwnershipEvent]:
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
    free_float_turnover: float | None,
    issued_turnover_5d: float,
    sudden_move_count: int,
) -> str:
    if (
        (rvol is not None and rvol >= 10)
        or (free_float_turnover is not None and free_float_turnover >= 0.50)
        or issued_turnover_5d >= 0.25
        or sudden_move_count >= 2
    ):
        return "VERY_HIGH"
    if (
        (rvol is not None and rvol >= 3)
        or (free_float_turnover is not None and free_float_turnover >= 0.25)
        or issued_turnover_5d >= 0.10
        or sudden_move_count >= 1
    ):
        return "HIGH"
    return "MODERATE"


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
    absolute_change = sum(abs(item.ownership_delta_pct or 0.0) for item in changes)
    major_holder_reduction = sum(
        -(item.ownership_delta_pct or 0.0)
        for item in changes
        if item.holder_role == "MAJOR_HOLDER" and (item.ownership_delta_pct or 0.0) < 0
    )
    exits = sum(
        1
        for item in changes
        if item.holder_role == "MAJOR_HOLDER"
        and item.previous_pct is not None
        and item.previous_pct >= 5
        and item.current_pct == 0
    )
    block_shares = sum(
        item.shares or 0
        for item in official_events
        if item.event_type in {"AGREED_TRADE", "BLOCK_TRADE"}
    )
    block_pct_issued = block_shares / issued_shares if block_shares else 0.0
    block_pct_free_float = (
        block_shares / free_float_shares
        if block_shares and free_float_shares
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
    if block_pct_issued >= 0.20:
        reasons.append("CONTROL_RELEVANT_BLOCK_GE_20PCT_ISSUED")
    elif block_pct_issued >= 0.10:
        reasons.append("MATERIAL_BLOCK_GE_10PCT_ISSUED")
    if block_pct_free_float is not None and block_pct_free_float >= 0.40:
        reasons.append("BLOCK_GE_40PCT_FREE_FLOAT")
    if exits:
        reasons.append("MAJOR_HOLDER_EXIT")
    if major_holder_reduction >= 5:
        reasons.append("CUMULATIVE_MAJOR_HOLDER_REDUCTION_GE_5PP")
    if insider_supply_events >= 2:
        reasons.append("INSIDER_OR_AFFILIATE_SUPPLY_CLUSTER")
    if block_pct_issued >= 0.10 or exits:
        state = "CONFIRMED_CONTROL_RELEVANT_EVENT"
    elif major_holder_reduction >= 5 or absolute_change >= 5 or insider_supply_events >= 2:
        state = "CONFIRMED_MATERIAL_OWNERSHIP_EVENT"
    elif official_events:
        state = "OFFICIAL_EVENT_OBSERVED"
    else:
        state = "NONE_OBSERVED"
    metrics = {
        "official_ownership_event_count_180d": len(official_events),
        "ownership_net_change_pct_points_180d": net_change,
        "ownership_absolute_change_pct_points_180d": absolute_change,
        "major_holder_reduction_pct_points_180d": major_holder_reduction,
        "major_holder_exit_count_180d": exits,
        "insider_affiliate_supply_event_count_180d": insider_supply_events,
        "block_shares_180d": block_shares,
        "block_pct_issued_shares_180d": block_pct_issued,
        "block_pct_free_float_180d": block_pct_free_float,
    }
    return state, reasons, metrics


def _directional_state(
    snapshot: SessionSnapshot | None,
    *,
    rvol: float | None,
) -> tuple[str, list[str], dict[str, Any]]:
    if snapshot is None:
        return "NOT_OBSERVED", [], {
            "gap_pct": None,
            "session_return_pct": None,
            "close_location_value": None,
            "high_to_last_giveback_pct": None,
            "vwap_fils": None,
            "last_vs_vwap_pct": None,
            "relative_strength_vs_market_pct_points": None,
            "relative_strength_vs_sector_pct_points": None,
        }
    gap = snapshot.open_fils / snapshot.previous_close_fils - 1.0
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
        session_return - snapshot.market_return_pct
        if snapshot.market_return_pct is not None
        else None
    )
    relative_sector = (
        session_return - snapshot.sector_return_pct
        if snapshot.sector_return_pct is not None
        else None
    )
    reasons: list[str] = []
    positive_support = (
        close_location >= 0.60
        or (
            relative_market is not None
            and relative_market >= 0.05
            and (last_vs_vwap is None or last_vs_vwap >= -0.01)
        )
    )
    negative_support = (
        close_location <= 0.40
        or (
            relative_market is not None
            and relative_market <= -0.05
            and (last_vs_vwap is None or last_vs_vwap <= 0.01)
        )
    )
    if session_return >= 0.03 and (rvol is None or rvol >= 3) and positive_support:
        state = "POSITIVE_CONFIRMED"
        reasons.append("POSITIVE_PRICE_VOLUME_CONFIRMATION")
    elif session_return <= -0.03 and (rvol is None or rvol >= 3) and negative_support:
        state = "NEGATIVE_CONFIRMED"
        reasons.append("NEGATIVE_PRICE_VOLUME_CONFIRMATION")
    elif session_return >= 0.01:
        state = "TENTATIVE_POSITIVE"
    elif session_return <= -0.01:
        state = "TENTATIVE_NEGATIVE"
    else:
        state = "UNCONFIRMED"
    if abs(gap) >= 0.03:
        reasons.append("MATERIAL_OPENING_GAP")
    if relative_market is not None and abs(relative_market) >= 0.05:
        reasons.append("STOCK_SPECIFIC_RELATIVE_STRENGTH")
    return state, reasons, {
        "gap_pct": gap,
        "session_return_pct": session_return,
        "close_location_value": close_location,
        "high_to_last_giveback_pct": giveback,
        "vwap_fils": vwap,
        "last_vs_vwap_pct": last_vs_vwap,
        "relative_strength_vs_market_pct_points": relative_market,
        "relative_strength_vs_sector_pct_points": relative_sector,
    }


def _continuation_state(
    directional_state: str,
    directional_metrics: dict[str, Any],
    *,
    rvol: float | None,
) -> tuple[str, list[str]]:
    if directional_state not in {"POSITIVE_CONFIRMED", "NEGATIVE_CONFIRMED"}:
        return "NOT_APPLICABLE", []
    giveback = directional_metrics["high_to_last_giveback_pct"]
    close_location = directional_metrics["close_location_value"]
    last_vs_vwap = directional_metrics["last_vs_vwap_pct"]
    reasons: list[str] = []
    if directional_state == "POSITIVE_CONFIRMED":
        if (
            (giveback is not None and giveback >= 0.10)
            or (close_location is not None and close_location < 0.55)
            or (last_vs_vwap is not None and last_vs_vwap < -0.01)
        ) and (rvol is None or rvol >= 5):
            reasons.append("VOLUME_CLIMAX_OR_DISTRIBUTION_RISK")
            return "ELEVATED_REVERSAL_RISK", reasons
        if (
            close_location is not None
            and close_location >= 0.75
            and (last_vs_vwap is None or last_vs_vwap >= 0)
        ):
            return "HEALTHY_CONTINUATION_STRUCTURE", []
        return "MIXED_CONTINUATION_STRUCTURE", []
    if close_location is not None and close_location <= 0.25:
        return "NEGATIVE_CONTINUATION_STRUCTURE", []
    return "MIXED_CONTINUATION_STRUCTURE", []


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
    bars = sorted(
        list(historical_bars),
        key=lambda item: parse_iso_date(item.session_date, "session_date"),
    )
    if len(bars) < 5:
        raise ValueError("at least five historical bars are required")
    if any(item.security_code != code for item in bars):
        raise ValueError("historical bar security_code mismatch")
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
        snapshot_date = parse_iso_date(session_snapshot.session_date, "session_date")
        if any(parse_iso_date(item.session_date, "session_date") >= snapshot_date for item in bars):
            raise ValueError("historical bars must precede the session snapshot")
        if parse_aware(session_snapshot.available_at, "available_at") > cutoff:
            raise ValueError("session snapshot was not available at decision_at")
        if capture_mode == "PROSPECTIVE" and parse_aware(
            session_snapshot.captured_at, "captured_at"
        ) > cutoff:
            raise ValueError("prospective session snapshot captured after decision_at")

    canonical, conflicts = _canonical_events(ownership_events, decision_at=cutoff)
    if any(item.security_code != code for item in canonical):
        raise ValueError("ownership event security_code mismatch")
    official_180 = [
        item for item in _window(canonical, cutoff, 180) if item.source_role in FACT_ROLES
    ]
    context_180 = [
        item for item in _window(canonical, cutoff, 180) if item.source_role not in FACT_ROLES
    ]

    historical_volumes = [item.volume for item in bars[-20:]]
    median_volume_20 = _median_positive(historical_volumes)
    rvol = (
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
    issued_turnover_5d = trailing_5_volume / capital_structure.issued_shares
    free_float_turnover_5d = (
        trailing_5_volume / capital_structure.free_float_shares
        if capital_structure.free_float_shares
        else None
    )
    session_issued_turnover = (
        session_snapshot.volume / capital_structure.issued_shares
        if session_snapshot is not None
        else None
    )
    session_free_float_turnover = (
        session_snapshot.volume / capital_structure.free_float_shares
        if session_snapshot is not None and capital_structure.free_float_shares
        else None
    )
    returns = _daily_returns(bars[-61:])
    sudden_move_count = sum(abs(value) >= 0.10 for value in returns)
    volatility = (
        math.sqrt(sum(value * value for value in returns) / len(returns))
        if returns
        else None
    )
    movement_risk = _risk_label(
        rvol=rvol,
        free_float_turnover=session_free_float_turnover,
        issued_turnover_5d=issued_turnover_5d,
        sudden_move_count=sudden_move_count,
    )
    ownership_state, ownership_reasons, ownership_metrics = _ownership_state(
        official_180,
        issued_shares=capital_structure.issued_shares,
        free_float_shares=capital_structure.free_float_shares,
    )
    directional_state, directional_reasons, directional_metrics = _directional_state(
        session_snapshot, rvol=rvol
    )
    continuation_state, continuation_reasons = _continuation_state(
        directional_state, directional_metrics, rvol=rvol
    )

    reason_codes = list(ownership_reasons + directional_reasons + continuation_reasons)
    if rvol is not None and rvol >= 10:
        reason_codes.append("EXTREME_RELATIVE_VOLUME_GE_10X")
    elif rvol is not None and rvol >= 3:
        reason_codes.append("HIGH_RELATIVE_VOLUME_GE_3X")
    if session_free_float_turnover is not None and session_free_float_turnover >= 1:
        reason_codes.append("FULL_FREE_FLOAT_ROTATION_GE_100PCT")
    elif session_free_float_turnover is not None and session_free_float_turnover >= 0.50:
        reason_codes.append("EXTREME_FREE_FLOAT_ROTATION_GE_50PCT")
    if issued_turnover_5d >= 0.10:
        reason_codes.append("CUMULATIVE_5D_TURNOVER_GE_10PCT_ISSUED")
    if context_180 and not official_180:
        reason_codes.append("CONTEXT_ONLY_OWNERSHIP_LEADS")
    if capital_structure.free_float_shares is None:
        reason_codes.append("FREE_FLOAT_MISSING")
    if conflicts:
        reason_codes.append("CONFLICTING_CANONICAL_EVENT_PAYLOAD")

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

    evidence_status = "CONFLICT" if conflicts else (
        "PARTIAL"
        if capital_structure.free_float_shares is None
        or any(item.source_role not in FACT_ROLES for item in canonical)
        else "COMPLETE"
    )
    metrics = {
        **ownership_metrics,
        **directional_metrics,
        "median_volume_20d": median_volume_20,
        "relative_volume_20d": rvol,
        "session_turnover_pct_issued": session_issued_turnover,
        "session_turnover_pct_free_float": session_free_float_turnover,
        "cumulative_turnover_5d_pct_issued": issued_turnover_5d,
        "cumulative_turnover_5d_pct_free_float": free_float_turnover_5d,
        "realized_rms_daily_return_60d": volatility,
        "sudden_move_count_60d": sudden_move_count,
        "context_only_event_count_180d": len(context_180),
    }
    evidence_hashes = sorted(
        set(capital_structure.evidence_hashes)
        | {item.evidence_hash for item in bars}
        | {item.evidence_hash for item in canonical}
        | ({session_snapshot.evidence_hash} if session_snapshot is not None else set())
    )
    return {
        "schema_version": "1.0",
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
        },
        "metrics": metrics,
        "reason_codes": sorted(set(reason_codes)),
        "conflicting_canonical_event_ids": conflicts,
        "evidence_hashes": evidence_hashes,
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


__all__ = [
    "CapitalStructure",
    "HistoricalBar",
    "OwnershipEvent",
    "SessionSnapshot",
    "analyze_ownership_turnover",
    "capital_structure_from_dict",
    "historical_bar_from_dict",
    "ownership_event_from_dict",
    "scan_ownership_turnover_universe",
    "session_snapshot_from_dict",
]
