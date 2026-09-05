from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Iterable

from .strict import finite_number, parse_aware, parse_iso_date


SOURCE_ROLES = frozenset(
    {
        "ISSUER_PRIMARY",
        "REGULATOR_OR_EXCHANGE",
        "LICENSED_MARKET_DATA",
        "SECONDARY_MARKET_DATA",
        "FINANCIAL_CONTEXT",
        "NEWS_CONTEXT",
        "DRIVE_ARCHIVE",
        "MODEL_INFERENCE",
    }
)
CAPTURE_MODES = frozenset({"PROSPECTIVE", "HISTORICAL_POINT_IN_TIME"})
CLAIM_KINDS = frozenset({"NUMBER", "TEXT", "DATE", "BOOLEAN"})
FACT_STATUSES = frozenset(
    {
        "RESOLVED",
        "SINGLE_SOURCE",
        "CONFLICT",
        "MISSING",
        "INFERRED_ONLY",
    }
)
INFERENCE_CONFIDENCE = frozenset({"LOW", "MEDIUM", "HIGH"})

ROLE_PRIORITY = {
    "ISSUER_PRIMARY": 0,
    "REGULATOR_OR_EXCHANGE": 1,
    "LICENSED_MARKET_DATA": 2,
    "SECONDARY_MARKET_DATA": 3,
    "FINANCIAL_CONTEXT": 4,
    "NEWS_CONTEXT": 5,
    "DRIVE_ARCHIVE": 6,
    "MODEL_INFERENCE": 7,
}


@dataclass(frozen=True)
class SourceObservation:
    observation_id: str
    security_code: str
    ticker: str
    claim_key: str
    value: Any
    unit: str
    source_id: str
    source_family: str
    origin_family: str
    source_role: str
    session_date: str | None
    as_of_date: str | None
    first_available_at: str
    captured_at: str
    legal_access: bool
    semantic_complete: bool
    timestamp_complete: bool
    value_unlocked: bool
    evidence_ref: str

    @property
    def independence_key(self) -> str:
        return self.origin_family or self.source_family

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClaimPolicy:
    claim_key: str
    kind: str
    unit: str
    allowed_roles: tuple[str, ...]
    minimum_independent_families: int = 2
    single_source_authority_roles: tuple[str, ...] = ()
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    requires_session_date: bool = False
    target_session_date: str | None = None
    archive_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.claim_key.strip():
            raise ValueError("claim_key is required")
        if self.kind not in CLAIM_KINDS:
            raise ValueError("invalid claim kind")
        if not self.unit.strip():
            raise ValueError("claim unit is required")
        if self.minimum_independent_families < 1:
            raise ValueError("minimum_independent_families must be >= 1")
        if set(self.allowed_roles) - SOURCE_ROLES:
            raise ValueError("claim policy contains invalid allowed_roles")
        if set(self.single_source_authority_roles) - set(self.allowed_roles):
            raise ValueError("single-source authority role must also be allowed")
        if self.absolute_tolerance < 0 or self.relative_tolerance < 0:
            raise ValueError("tolerances cannot be negative")
        if self.target_session_date is not None:
            parse_iso_date(self.target_session_date, "target_session_date")


@dataclass(frozen=True)
class ProposedInference:
    claim_key: str
    proposed_value: Any
    unit: str
    confidence: str
    method: str
    assumptions: tuple[str, ...]
    supported_by_claims: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.claim_key.strip() or not self.method.strip():
            raise ValueError("inference claim_key and method are required")
        if self.confidence not in INFERENCE_CONFIDENCE:
            raise ValueError("invalid inference confidence")
        if not self.unit.strip():
            raise ValueError("inference unit is required")
        if not self.assumptions:
            raise ValueError("inference assumptions are required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def observation_from_dict(row: dict[str, Any]) -> SourceObservation:
    required_text = {
        field: str(row.get(field, "")).strip()
        for field in (
            "observation_id",
            "security_code",
            "ticker",
            "claim_key",
            "unit",
            "source_id",
            "source_family",
            "origin_family",
            "source_role",
            "evidence_ref",
        )
    }
    missing = [field for field, value in required_text.items() if not value]
    if missing:
        raise ValueError(f"missing observation fields: {', '.join(sorted(missing))}")
    role = required_text["source_role"].upper()
    if role not in SOURCE_ROLES:
        raise ValueError("invalid source_role")
    available = parse_aware(row.get("first_available_at"), "first_available_at")
    captured = parse_aware(row.get("captured_at"), "captured_at")
    if captured < available:
        raise ValueError("captured_at precedes first_available_at")
    session_value = row.get("session_date")
    session_date = None
    if session_value not in (None, ""):
        session_date = parse_iso_date(session_value, "session_date").isoformat()
    as_of_value = row.get("as_of_date")
    as_of_date = None
    if as_of_value not in (None, ""):
        as_of_date = parse_iso_date(as_of_value, "as_of_date").isoformat()
    flags: dict[str, bool] = {}
    for field in (
        "legal_access",
        "semantic_complete",
        "timestamp_complete",
        "value_unlocked",
    ):
        value = row.get(field)
        if type(value) is not bool:
            raise ValueError(f"{field} must be a JSON boolean")
        flags[field] = value
    return SourceObservation(
        observation_id=required_text["observation_id"],
        security_code=required_text["security_code"],
        ticker=required_text["ticker"].upper(),
        claim_key=required_text["claim_key"],
        value=row.get("value"),
        unit=required_text["unit"],
        source_id=required_text["source_id"],
        source_family=required_text["source_family"],
        origin_family=required_text["origin_family"],
        source_role=role,
        session_date=session_date,
        as_of_date=as_of_date,
        first_available_at=available.isoformat(),
        captured_at=captured.isoformat(),
        legal_access=flags["legal_access"],
        semantic_complete=flags["semantic_complete"],
        timestamp_complete=flags["timestamp_complete"],
        value_unlocked=flags["value_unlocked"],
        evidence_ref=required_text["evidence_ref"],
    )


def _normalized_value(value: Any, policy: ClaimPolicy) -> Any:
    if policy.kind == "NUMBER":
        return finite_number(value, policy.claim_key)
    if policy.kind == "TEXT":
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError(f"{policy.claim_key} text is empty")
        return text
    if policy.kind == "DATE":
        return parse_iso_date(value, policy.claim_key).isoformat()
    if type(value) is not bool:
        raise ValueError(f"{policy.claim_key} must be boolean")
    return value


def _equivalent(left: Any, right: Any, policy: ClaimPolicy) -> bool:
    if policy.kind == "NUMBER":
        left_num = float(left)
        right_num = float(right)
        difference = abs(left_num - right_num)
        scale = max(abs(left_num), abs(right_num), 1.0)
        return (
            difference <= policy.absolute_tolerance
            or difference <= policy.relative_tolerance * scale
        )
    if policy.kind == "TEXT":
        return str(left).casefold() == str(right).casefold()
    return left == right


def _eligibility_reason(
    observation: SourceObservation,
    *,
    policy: ClaimPolicy,
    decision_at: datetime,
    capture_mode: str,
) -> str | None:
    if observation.claim_key != policy.claim_key:
        return "CLAIM_KEY_MISMATCH"
    if observation.source_role not in policy.allowed_roles:
        return "SOURCE_ROLE_NOT_ALLOWED"
    if observation.source_role == "MODEL_INFERENCE":
        return "INFERENCE_IS_NOT_FACT_EVIDENCE"
    if not observation.legal_access:
        return "ACCESS_NOT_LEGAL_OR_AUTHORIZED"
    if not observation.semantic_complete:
        return "SEMANTIC_CONTENT_INCOMPLETE"
    if not observation.timestamp_complete:
        return "TIMESTAMP_INCOMPLETE"
    if not observation.value_unlocked:
        return "VALUE_LOCKED_OR_MASKED"
    if observation.source_role == "DRIVE_ARCHIVE" and not policy.archive_allowed:
        return "ARCHIVE_NOT_ALLOWED_FOR_THIS_CLAIM"
    available = parse_aware(observation.first_available_at, "first_available_at")
    captured = parse_aware(observation.captured_at, "captured_at")
    if available > decision_at:
        return "NOT_AVAILABLE_AT_DECISION_TIME"
    if capture_mode == "PROSPECTIVE" and captured > decision_at:
        return "CAPTURED_AFTER_DECISION_TIME"
    if policy.requires_session_date and observation.session_date is None:
        return "SESSION_DATE_REQUIRED"
    if policy.target_session_date is not None:
        if observation.session_date != policy.target_session_date:
            return "STALE_OR_WRONG_SESSION"
    if observation.unit != policy.unit:
        return "UNIT_MISMATCH"
    try:
        _normalized_value(observation.value, policy)
    except ValueError:
        return "VALUE_INVALID"
    return None


def _choose_family_representatives(
    observations: list[SourceObservation], policy: ClaimPolicy
) -> tuple[list[SourceObservation], list[dict[str, Any]]]:
    by_family: dict[str, list[SourceObservation]] = {}
    for observation in observations:
        by_family.setdefault(observation.independence_key, []).append(observation)
    representatives: list[SourceObservation] = []
    family_conflicts: list[dict[str, Any]] = []
    for family, rows in sorted(by_family.items()):
        rows.sort(
            key=lambda item: (
                ROLE_PRIORITY[item.source_role],
                parse_aware(item.first_available_at, "first_available_at"),
                item.observation_id,
            )
        )
        values = [_normalized_value(item.value, policy) for item in rows]
        first = values[0]
        if any(not _equivalent(first, value, policy) for value in values[1:]):
            family_conflicts.append(
                {
                    "independence_key": family,
                    "observation_ids": [item.observation_id for item in rows],
                    "values": values,
                    "reason": "INTRA_FAMILY_CONFLICT",
                }
            )
            continue
        representatives.append(rows[0])
    return representatives, family_conflicts


def _clusters(
    representatives: list[SourceObservation], policy: ClaimPolicy
) -> list[list[SourceObservation]]:
    clusters: list[list[SourceObservation]] = []
    for observation in sorted(
        representatives,
        key=lambda item: (
            ROLE_PRIORITY[item.source_role],
            item.independence_key,
            item.observation_id,
        ),
    ):
        value = _normalized_value(observation.value, policy)
        placed = False
        for cluster in clusters:
            reference_values = [
                _normalized_value(item.value, policy) for item in cluster
            ]
            if policy.kind == "NUMBER":
                reference = median(float(item) for item in reference_values)
            else:
                reference = reference_values[0]
            if _equivalent(value, reference, policy):
                cluster.append(observation)
                placed = True
                break
        if not placed:
            clusters.append([observation])
    clusters.sort(
        key=lambda cluster: (
            -len(cluster),
            min(ROLE_PRIORITY[item.source_role] for item in cluster),
            min(item.independence_key for item in cluster),
        )
    )
    return clusters


def _resolved_value(cluster: list[SourceObservation], policy: ClaimPolicy) -> Any:
    values = [_normalized_value(item.value, policy) for item in cluster]
    if policy.kind == "NUMBER":
        return median(float(value) for value in values)
    return values[0]


def aggregate_claim(
    *,
    observations: Iterable[SourceObservation],
    policy: ClaimPolicy,
    decision_at: str,
    capture_mode: str,
    inference: ProposedInference | None = None,
) -> dict[str, Any]:
    if capture_mode not in CAPTURE_MODES:
        raise ValueError("invalid capture_mode")
    cutoff = parse_aware(decision_at, "decision_at")
    rows = list(observations)
    if inference is not None:
        if inference.claim_key != policy.claim_key or inference.unit != policy.unit:
            raise ValueError("inference does not match claim policy")
    observation_ids = [item.observation_id for item in rows]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("duplicate observation_id")
    excluded: list[dict[str, Any]] = []
    eligible: list[SourceObservation] = []
    for observation in rows:
        reason = _eligibility_reason(
            observation,
            policy=policy,
            decision_at=cutoff,
            capture_mode=capture_mode,
        )
        if reason is None:
            eligible.append(observation)
        else:
            excluded.append(
                {
                    "observation_id": observation.observation_id,
                    "source_family": observation.source_family,
                    "source_role": observation.source_role,
                    "reason": reason,
                }
            )
    representatives, family_conflicts = _choose_family_representatives(
        eligible, policy
    )
    clusters = _clusters(representatives, policy)
    status = "MISSING"
    resolved: dict[str, Any] | None = None
    outliers: list[str] = []
    if clusters:
        leader = clusters[0]
        second_size = len(clusters[1]) if len(clusters) > 1 else 0
        authority_single = len(leader) == 1 and leader[0].source_role in set(
            policy.single_source_authority_roles
        )
        enough_sources = len(leader) >= policy.minimum_independent_families
        unique_leader = len(leader) > second_size
        if authority_single or (enough_sources and unique_leader):
            status = "RESOLVED"
            resolved = {
                "value": _resolved_value(leader, policy),
                "unit": policy.unit,
                "session_date": policy.target_session_date
                or leader[0].session_date,
                "independent_families": sorted(
                    {item.independence_key for item in leader}
                ),
                "observation_ids": sorted(item.observation_id for item in leader),
                "resolution_basis": (
                    "SINGLE_AUTHORITY_SOURCE"
                    if authority_single
                    else "MULTI_SOURCE_CONSENSUS"
                ),
            }
            leader_ids = {item.observation_id for item in leader}
            outliers = sorted(
                item.observation_id
                for cluster in clusters[1:]
                for item in cluster
                if item.observation_id not in leader_ids
            )
        elif len(representatives) == 1:
            status = "SINGLE_SOURCE"
        else:
            status = "CONFLICT"
    if family_conflicts and status == "MISSING":
        status = "CONFLICT"
    inference_payload: dict[str, Any] | None = None
    if inference is not None:
        inference_payload = inference.to_dict()
        inference_payload["fact_precedence"] = status == "RESOLVED"
        inference_payload["may_overwrite_fact"] = False
        if status == "MISSING":
            status = "INFERRED_ONLY"
    if status not in FACT_STATUSES:
        raise AssertionError("unexpected fact status")
    return {
        "claim_key": policy.claim_key,
        "status": status,
        "resolved": resolved,
        "inference": inference_payload,
        "eligible_observation_ids": sorted(
            item.observation_id for item in eligible
        ),
        "independent_family_count": len(
            {item.independence_key for item in representatives}
        ),
        "source_families": sorted(
            {item.source_family for item in eligible}
        ),
        "source_roles": sorted({item.source_role for item in eligible}),
        "family_conflicts": family_conflicts,
        "outlier_observation_ids": outliers,
        "excluded": sorted(
            excluded, key=lambda item: (item["reason"], item["observation_id"])
        ),
        "fact_usable": status == "RESOLVED",
        "execution_eligible": False,
    }


def aggregate_security_claims(
    *,
    security_code: str,
    ticker: str,
    observations: Iterable[SourceObservation],
    policies: Iterable[ClaimPolicy],
    decision_at: str,
    capture_mode: str,
    inferences: Iterable[ProposedInference] = (),
) -> dict[str, Any]:
    rows = list(observations)
    code = str(security_code).strip()
    ticker_text = str(ticker).strip().upper()
    if not code or not ticker_text:
        raise ValueError("security_code and ticker are required")
    if any(item.security_code != code or item.ticker != ticker_text for item in rows):
        raise ValueError("observation security identity mismatch")
    policy_rows = list(policies)
    policy_keys = [item.claim_key for item in policy_rows]
    if len(policy_keys) != len(set(policy_keys)):
        raise ValueError("duplicate claim policy")
    inference_map: dict[str, ProposedInference] = {}
    for inference in inferences:
        if inference.claim_key in inference_map:
            raise ValueError("duplicate inference claim_key")
        inference_map[inference.claim_key] = inference
    claims: dict[str, dict[str, Any]] = {}
    for policy in policy_rows:
        claims[policy.claim_key] = aggregate_claim(
            observations=[item for item in rows if item.claim_key == policy.claim_key],
            policy=policy,
            decision_at=decision_at,
            capture_mode=capture_mode,
            inference=inference_map.get(policy.claim_key),
        )
    unresolved = sorted(
        key for key, value in claims.items() if not value["fact_usable"]
    )
    conflicts = sorted(
        key for key, value in claims.items() if value["status"] == "CONFLICT"
    )
    inferred_only = sorted(
        key for key, value in claims.items() if value["status"] == "INFERRED_ONLY"
    )
    source_coverage = {
        "observation_count": len(rows),
        "source_family_count": len({item.source_family for item in rows}),
        "independent_origin_count": len({item.independence_key for item in rows}),
        "roles": sorted({item.source_role for item in rows}),
    }
    return {
        "schema_version": "1.0",
        "method_id": "multi_source_claim_aggregation_v1",
        "storage_mode": "IN_MEMORY_ONLY",
        "security_code": code,
        "ticker": ticker_text,
        "decision_at": parse_aware(decision_at, "decision_at").isoformat(),
        "capture_mode": capture_mode,
        "claims": claims,
        "unresolved_claims": unresolved,
        "conflicting_claims": conflicts,
        "inferred_only_claims": inferred_only,
        "source_coverage": source_coverage,
        "overall_status": "COMPLETE" if not unresolved else "PARTIAL",
        "claim_boundaries": {
            "local_persistence": False,
            "drive_persistence": False,
            "silent_gap_filling": False,
            "inference_is_fact": False,
            "execution": False,
        },
    }


__all__ = [
    "ClaimPolicy",
    "ProposedInference",
    "SourceObservation",
    "aggregate_claim",
    "aggregate_security_claims",
    "observation_from_dict",
]
