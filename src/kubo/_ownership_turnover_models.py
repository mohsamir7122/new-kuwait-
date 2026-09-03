from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .events import SOURCE_ROLES
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
# Pre-open and opening-auction data require a separate indicative-auction contract.
MARKET_PHASES = frozenset({"CONTINUOUS_TRADING", "CLOSING_AUCTION", "CLOSED"})
CAPTURE_MODES = frozenset({"PROSPECTIVE", "HISTORICAL_POINT_IN_TIME"})
RANK_ORDER = {
    "EVENT_CONFIRMED": 0,
    "HUMAN_REVIEW_REQUIRED": 1,
    "DISCOVERY_ALERT": 2,
    "HIGH_PRIORITY_WATCH": 3,
    "ANOMALY_WATCH": 4,
    "ABSTAIN": 5,
}
METHOD_ID = "ownership_turnover_radar_v1"
THRESHOLDS: dict[str, float] = {
    "relative_volume_high": 3.0,
    "relative_volume_extreme": 10.0,
    "relative_volume_activity_extreme": 5.0,
    "session_issued_turnover_confirmation": 0.10,
    "session_free_float_turnover_high": 0.25,
    "session_free_float_turnover_extreme": 0.50,
    "session_free_float_turnover_full_rotation": 1.0,
    "cumulative_5d_issued_turnover_high": 0.10,
    "cumulative_5d_issued_turnover_extreme": 0.25,
    "block_issued_material": 0.10,
    "block_issued_control_relevant": 0.20,
    "block_free_float_material": 0.40,
    "major_holder_reduction_material_pp": 5.0,
    "directional_return_confirmation": 0.03,
    "relative_strength_material": 0.05,
    "opening_gap_material": 0.03,
    "giveback_warning": 0.10,
    "close_location_positive_support": 0.60,
    "close_location_negative_support": 0.40,
    "close_location_continuation_healthy": 0.75,
    "close_location_distribution_warning": 0.55,
    "vwap_support_tolerance": 0.01,
    "tentative_directional_return": 0.01,
    "sudden_move_return": 0.10,
    "sudden_move_count_high": 1.0,
    "sudden_move_count_extreme": 2.0,
    "timeline_continuity_tolerance_pp": 0.05,
}


@dataclass(frozen=True)
class CapitalStructure:
    security_code: str
    issued_shares: int
    free_float_shares: int | None
    as_of: str
    first_available_at: str
    captured_at: str
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
    market_return_fraction: float | None
    sector_return_fraction: float | None
    available_at: str
    captured_at: str
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _positive_int(value: Any, field: str) -> int:
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
    else:
        raise ValueError(f"{field} must be a positive integer")
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
    else:
        raise ValueError(f"{field} must be a non-negative integer")
    if parsed < 0:
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


def _unique_resolved_hashes(
    values: Any, *, field: str, manifest_hashes: frozenset[str]
) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{field} must be a non-empty list")
    hashes = tuple(require_sha256(value, f"{field}.item") for value in values)
    if len(hashes) != len(set(hashes)):
        raise ValueError(f"{field} must not contain duplicates")
    if set(hashes) - manifest_hashes:
        raise ValueError(f"{field} does not resolve")
    return tuple(sorted(hashes))


def capital_structure_from_dict(
    row: dict[str, Any], *, manifest_hashes: frozenset[str], decision_at: str
) -> CapitalStructure:
    security_code = str(row.get("security_code", "")).strip()
    if not security_code:
        raise ValueError("capital_structure.security_code is required")
    issued = _positive_int(row.get("issued_shares"), "capital_structure.issued_shares")
    free_float_value = row.get("free_float_shares")
    free_float = (
        None
        if free_float_value in (None, "")
        else _positive_int(free_float_value, "capital_structure.free_float_shares")
    )
    if free_float is not None and free_float > issued:
        raise ValueError("free_float_shares cannot exceed issued_shares")
    decision = parse_aware(decision_at, "decision_at")
    as_of = parse_aware(row.get("as_of"), "capital_structure.as_of")
    available = parse_aware(
        row.get("first_available_at"), "capital_structure.first_available_at"
    )
    captured = parse_aware(row.get("captured_at"), "capital_structure.captured_at")
    if as_of > decision:
        raise ValueError("capital structure as_of occurs after decision_at")
    if available > decision:
        raise ValueError("capital structure was not available at decision_at")
    if captured < available:
        raise ValueError("capital structure captured_at precedes first_available_at")
    hashes = _unique_resolved_hashes(
        row.get("evidence_hashes"),
        field="capital_structure.evidence_hashes",
        manifest_hashes=manifest_hashes,
    )
    return CapitalStructure(
        security_code=security_code,
        issued_shares=issued,
        free_float_shares=free_float,
        as_of=as_of.isoformat(),
        first_available_at=available.isoformat(),
        captured_at=captured.isoformat(),
        evidence_hashes=hashes,
    )


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
    holder_id = _optional_text(row.get("holder_id"))
    if event_type == "BENEFICIAL_OWNERSHIP_CHANGE":
        if previous_pct is None or current_pct is None or holder_id is None:
            raise ValueError(
                "ownership change requires holder_id, previous_pct, and current_pct"
            )
        if abs(current_pct - previous_pct) < 1e-12:
            raise ValueError("ownership change must change the disclosed percentage")
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
        holder_id=holder_id,
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
    if available.date() < session:
        raise ValueError("historical bar cannot be available before its session")
    if captured < available:
        raise ValueError("historical captured_at precedes available_at")
    evidence_hash = require_sha256(row.get("evidence_hash"), "historical.evidence_hash")
    if evidence_hash not in manifest_hashes:
        raise ValueError("historical evidence does not resolve")
    return HistoricalBar(
        security_code=security_code,
        session_date=session.isoformat(),
        close_fils=close,
        volume=volume,
        turnover_kwd=turnover,
        available_at=available.isoformat(),
        captured_at=captured.isoformat(),
        evidence_hash=evidence_hash,
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
        raise ValueError("invalid market_phase for traded-session snapshot")
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
    if trade_count is not None and ((volume > 0 and trade_count == 0) or (volume == 0 and trade_count > 0)):
        raise ValueError("snapshot trade_count is inconsistent with volume")
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
    if available.date() < session:
        raise ValueError("session snapshot cannot be available before its session")
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
        market_return_fraction=_optional_number(
            row.get("market_return_fraction"),
            "snapshot.market_return_fraction",
            minimum=-1,
            maximum=10,
        ),
        sector_return_fraction=_optional_number(
            row.get("sector_return_fraction"),
            "snapshot.sector_return_fraction",
            minimum=-1,
            maximum=10,
        ),
        available_at=available.isoformat(),
        captured_at=captured.isoformat(),
        evidence_hash=evidence_hash,
    )
