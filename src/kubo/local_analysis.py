from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .analysts import analyze_fundamentals, analyze_price_window, analyze_sentiment
from .atomic_output import run_atomic_output
from .events import event_from_dict
from .features import build_event_features, validate_feature_snapshot
from .foundation_io import load_strict_json_object, require_real_directory, safe_regular_file
from .hashing import canonical_json_bytes, hash_json, sha256_bytes
from .identity import IdentityRecord, IdentityResolver
from .liquidity import calculate_liquidity_metrics
from .strict import finite_number, parse_aware, parse_iso_date, require_sha256, safe_relative_path


REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "analysis_id",
        "decision_at",
        "capture_mode",
        "identity",
        "evidence",
        "prices",
        "events",
        "fundamentals",
        "sentiment",
    }
)
IDENTITY_KEYS = frozenset(
    {
        "security_code",
        "ticker",
        "isin",
        "name_ar",
        "name_en",
        "board",
        "market_segment",
        "currency",
        "valid_from",
        "valid_to",
        "listing_status",
        "evidence_sha256",
    }
)
PRICE_KEYS = frozenset(
    {"date", "close_fils", "volume", "turnover_kwd", "evidence_sha256"}
)
EVENT_KEYS = frozenset(
    {
        "event_id",
        "security_code",
        "source_id",
        "source_role",
        "event_type",
        "direction",
        "novelty",
        "event_at",
        "published_at",
        "first_available_at",
        "captured_at",
        "content_hash",
        "evidence_hash",
        "relation_type",
        "original_event_id",
        "raw_text",
    }
)
FUNDAMENTAL_KEYS = frozenset(
    {"revenue", "net_income", "operating_cash_flow", "total_debt", "equity"}
)
SENTIMENT_KEYS = frozenset(
    {"origin_id", "author_id", "tone", "author_reliability", "evidence_sha256"}
)
EVIDENCE_KEYS = frozenset({"path", "sha256"})
CAPTURE_MODES = frozenset({"PROSPECTIVE", "HISTORICAL_POINT_IN_TIME"})


def _exact_object(value: Any, expected: frozenset[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"{field} keys mismatch; missing={missing}; unknown={unknown}")
    return value


def _bounded_text(value: Any, field: str, *, maximum: int = 200) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(ord(character) < 32 for character in text):
        raise ValueError(f"{field} must be non-empty bounded text")
    return text


def _optional_date(value: Any, field: str) -> date | None:
    return None if value in (None, "") else parse_iso_date(value, field)


def _verify_evidence(bundle_root: Path, rows: Any) -> tuple[frozenset[str], list[dict[str, Any]]]:
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("evidence must contain between 1 and 32 entries")
    hashes: set[str] = set()
    paths: set[str] = set()
    inventory: list[dict[str, Any]] = []
    total_bytes = 0
    for index, value in enumerate(rows):
        row = _exact_object(value, EVIDENCE_KEYS, f"evidence[{index}]")
        relative = safe_relative_path(row["path"], f"evidence[{index}].path")
        path_text = relative.as_posix()
        if path_text == "request.json" or path_text in paths:
            raise ValueError("evidence paths must be unique and must not name request.json")
        expected = require_sha256(row["sha256"], f"evidence[{index}].sha256")
        if expected in hashes:
            raise ValueError("evidence hashes must be unique")
        content = safe_regular_file(
            bundle_root / relative,
            field=f"evidence file {path_text}",
            max_bytes=8 * 1024 * 1024,
        )
        actual = sha256_bytes(content)
        if actual != expected:
            raise ValueError(f"evidence hash mismatch: {path_text}")
        total_bytes += len(content)
        if total_bytes > 32 * 1024 * 1024:
            raise ValueError("evidence exceeds total byte budget")
        paths.add(path_text)
        hashes.add(expected)
        inventory.append({"path": path_text, "sha256": expected, "size_bytes": len(content)})
    return frozenset(hashes), sorted(inventory, key=lambda item: item["path"])


def _parse_identity(value: Any, evidence_hashes: frozenset[str], decision_day: date) -> IdentityRecord:
    row = _exact_object(value, IDENTITY_KEYS, "identity")
    raw_hash = require_sha256(row["evidence_sha256"], "identity.evidence_sha256")
    if raw_hash not in evidence_hashes:
        raise ValueError("identity evidence does not resolve")
    valid_from = parse_iso_date(row["valid_from"], "identity.valid_from")
    valid_to = _optional_date(row["valid_to"], "identity.valid_to")
    if valid_to is not None and valid_to < valid_from:
        raise ValueError("identity.valid_to precedes valid_from")
    record = IdentityRecord(
        security_code=_bounded_text(row["security_code"], "identity.security_code", maximum=32),
        ticker=_bounded_text(row["ticker"], "identity.ticker", maximum=32).upper(),
        isin=str(row["isin"] or "").strip().upper() or None,
        name_ar=str(row["name_ar"] or "").strip(),
        name_en=str(row["name_en"] or "").strip(),
        board=_bounded_text(row["board"], "identity.board", maximum=32).lower(),
        market_segment=_bounded_text(row["market_segment"], "identity.market_segment", maximum=64),
        currency=_bounded_text(row["currency"], "identity.currency", maximum=8).upper(),
        valid_from=valid_from,
        valid_to=valid_to,
        listing_status=_bounded_text(row["listing_status"], "identity.listing_status", maximum=32).upper(),
        raw_sha256=raw_hash,
    )
    if record.currency != "KWD":
        raise ValueError("identity.currency must be KWD")
    if record.listing_status not in {"ACTIVE", "LISTED", "TRADING", "SUSPENDED", "HALTED"}:
        raise ValueError("identity.listing_status is not eligible for local analysis")
    IdentityResolver([record]).resolve(
        as_of=decision_day,
        board=record.board,
        security_code=record.security_code,
        isin=record.isin,
        ticker=record.ticker,
    )
    return record


def _parse_prices(
    value: Any,
    evidence_hashes: frozenset[str],
    decision_day: date,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 5 <= len(value) <= 512:
        raise ValueError("prices must contain between 5 and 512 sessions")
    output: list[dict[str, Any]] = []
    previous: date | None = None
    for index, candidate in enumerate(value):
        row = _exact_object(candidate, PRICE_KEYS, f"prices[{index}]")
        session = parse_iso_date(row["date"], f"prices[{index}].date")
        if session > decision_day:
            raise ValueError("price session occurs after decision date")
        if previous is not None and session <= previous:
            raise ValueError("price sessions must be unique and strictly increasing")
        previous = session
        evidence = require_sha256(row["evidence_sha256"], f"prices[{index}].evidence_sha256")
        if evidence not in evidence_hashes:
            raise ValueError("price evidence does not resolve")
        close = finite_number(row["close_fils"], f"prices[{index}].close_fils", minimum=0.001)
        volume = row["volume"]
        turnover = row["turnover_kwd"]
        output.append(
            {
                "date": session.isoformat(),
                "close_fils": close,
                "volume": None if volume is None else finite_number(volume, f"prices[{index}].volume", minimum=0),
                "turnover_kwd": None if turnover is None else finite_number(turnover, f"prices[{index}].turnover_kwd", minimum=0),
                "evidence_sha256": evidence,
            }
        )
    return output


def _parse_fundamentals(value: Any, evidence_hashes: frozenset[str]) -> dict[str, Any] | None:
    if value is None:
        return None
    row = _exact_object(value, frozenset({"current", "prior", "evidence_sha256s"}), "fundamentals")
    hashes = row["evidence_sha256s"]
    if not isinstance(hashes, list) or not hashes:
        raise ValueError("fundamentals.evidence_sha256s must be a non-empty list")
    normalized = [require_sha256(item, "fundamentals.evidence_sha256") for item in hashes]
    if len(normalized) != len(set(normalized)) or set(normalized) - evidence_hashes:
        raise ValueError("fundamental evidence is duplicated or unresolved")
    current = _exact_object(row["current"], FUNDAMENTAL_KEYS, "fundamentals.current")
    prior = _exact_object(row["prior"], FUNDAMENTAL_KEYS, "fundamentals.prior")
    return {"current": current, "prior": prior, "evidence_sha256s": sorted(normalized)}


def _parse_sentiment(value: Any, evidence_hashes: frozenset[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("sentiment must be a list with at most 256 entries")
    output: list[dict[str, Any]] = []
    for index, candidate in enumerate(value):
        row = _exact_object(candidate, SENTIMENT_KEYS, f"sentiment[{index}]")
        evidence = require_sha256(row["evidence_sha256"], f"sentiment[{index}].evidence_sha256")
        if evidence not in evidence_hashes:
            raise ValueError("sentiment evidence does not resolve")
        output.append({key: row[key] for key in SENTIMENT_KEYS if key != "evidence_sha256"})
    return output


def analyze_local_bundle(bundle_root: Path) -> dict[str, Any]:
    root = require_real_directory(bundle_root, field="bundle_root")
    request, request_bytes = load_strict_json_object(
        root / "request.json",
        field="local analysis request",
        max_bytes=2 * 1024 * 1024,
    )
    request = _exact_object(request, REQUEST_KEYS, "request")
    if request["schema_version"] != "1.0":
        raise ValueError("request.schema_version must be 1.0")
    analysis_id = _bounded_text(request["analysis_id"], "analysis_id", maximum=128)
    decision = parse_aware(request["decision_at"], "decision_at")
    capture_mode = str(request["capture_mode"])
    if capture_mode not in CAPTURE_MODES:
        raise ValueError("capture_mode is invalid")
    evidence_hashes, evidence_inventory = _verify_evidence(root, request["evidence"])
    identity = _parse_identity(request["identity"], evidence_hashes, decision.date())
    prices = _parse_prices(request["prices"], evidence_hashes, decision.date())

    event_values = request["events"]
    if not isinstance(event_values, list) or len(event_values) > 512:
        raise ValueError("events must be a list with at most 512 entries")
    events = []
    for index, candidate in enumerate(event_values):
        row = _exact_object(candidate, EVENT_KEYS, f"events[{index}]")
        event = event_from_dict(row, manifest_hashes=evidence_hashes)
        if event.security_code != identity.security_code:
            raise ValueError("event security_code does not match identity")
        events.append(event)

    features = build_event_features(
        events,
        decision_id=analysis_id,
        security_code=identity.security_code,
        decision_at=decision.isoformat(),
        capture_mode=capture_mode,
    )
    feature_report = validate_feature_snapshot(features, manifest_hashes=evidence_hashes)
    if feature_report["status"] != "PASS":
        raise ValueError("event feature validation failed: " + ";".join(feature_report["errors"]))

    signals = [item.to_dict() for item in analyze_price_window(prices)]
    fundamentals = _parse_fundamentals(request["fundamentals"], evidence_hashes)
    if fundamentals is not None:
        signals.append(analyze_fundamentals(fundamentals["current"], fundamentals["prior"]).to_dict())
    sentiment = _parse_sentiment(request["sentiment"], evidence_hashes)
    signals.append(analyze_sentiment(sentiment).to_dict())

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_RESEARCH_SUMMARY",
        "analysis_id": analysis_id,
        "decision_at": decision.isoformat(),
        "capture_mode": capture_mode,
        "security": {
            "security_code": identity.security_code,
            "ticker": identity.ticker,
            "isin": identity.isin,
            "board": identity.board,
            "currency": identity.currency,
            "listing_status": identity.listing_status,
        },
        "request_sha256": sha256_bytes(request_bytes),
        "verified_evidence": evidence_inventory,
        "price_session_count": len(prices),
        "event_count": len(events),
        "signals": signals,
        "liquidity": calculate_liquidity_metrics(prices).to_dict(),
        "event_features": features,
        "feature_validation": feature_report,
        "claim_boundaries": {
            "live_collection": False,
            "probability": False,
            "recommendation": False,
            "ranking": False,
            "trade_execution": False,
            "output_class": "DESCRIPTIVE_RESEARCH_SUMMARY_ONLY",
        },
    }
    report["report_sha256"] = hash_json(report)
    return report


def write_local_analysis(bundle_root: Path, output_root: Path) -> dict[str, Any]:
    report = analyze_local_bundle(bundle_root)

    def worker(staging: Path) -> None:
        report_bytes = canonical_json_bytes(report)
        (staging / "report.json").write_bytes(report_bytes)
        manifest = {
            "schema_version": "1.0",
            "status": "PASS",
            "artifacts": [
                {
                    "path": "report.json",
                    "sha256": sha256_bytes(report_bytes),
                    "size_bytes": len(report_bytes),
                }
            ],
        }
        (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))

    run_atomic_output(output_root, worker)
    return report


__all__ = ["analyze_local_bundle", "write_local_analysis"]
