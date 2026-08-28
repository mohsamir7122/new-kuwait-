from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any


SOURCE_SHA = "8860989f6a2affdc66bc790f639757c9a897f353"

MIGRATED_MODULES = frozenset(
    {
        "analysts",
        "atomic_output",
        "ca_adjustments",
        "events",
        "evidence_hashes",
        "features",
        "foundation_io",
        "hashing",
        "identity",
        "liquidity",
        "official_parsers",
        "outcome_evidence",
        "portfolio_state",
        "provenance",
        "research_price_history",
        "runtime_trust",
        "source_resilience",
        "status_corporate_parsers",
        "status_history",
        "strict",
        "temporal_validation",
    }
)
REPLACED_MODULES = frozenset({"__init__", "__main__", "cli", "cli_v3"})

BRANCH_AUDIT = (
    {
        "refs": ["origin/agent/bootstrap-archive-v0.1"],
        "head": "b9145b2",
        "focused_tests": 34,
        "test_status": "PASS",
        "disposition": "EXCLUDED_LEGACY_BOOTSTRAP_SCOPE",
    },
    {
        "refs": ["origin/agent/final-price-collection-test"],
        "head": "d0bf6ff",
        "focused_tests": 58,
        "test_status": "PASS",
        "disposition": "EXCLUDED_STALE_LIVE_COLLECTION",
    },
    {
        "refs": ["origin/agent/humansoft-event-factor-panel-v1"],
        "head": "7a74058",
        "focused_tests": 28,
        "passing_tests": 26,
        "test_status": "FAIL",
        "disposition": "REJECTED_TEST_FAILURE",
        "reason": "two expectations preserve misspelled STARTD values while runtime emits STARTED",
    },
    {
        "refs": ["origin/agent/ku-bo-015-source-access-recipes"],
        "head": "6aa50ac",
        "focused_tests": 22,
        "test_status": "PASS",
        "disposition": "SUPERSEDED_BY_MAIN",
    },
    {
        "refs": ["origin/agent/ku-bo-016-codex-live-bootstrap"],
        "head": "6e9ab87",
        "focused_tests": 43,
        "test_status": "PASS",
        "disposition": "SUPERSEDED_BY_MAIN",
    },
    {
        "refs": ["origin/agent/ku-bo-017-live-dry-run-orchestrator"],
        "head": "d71314e",
        "focused_tests": 72,
        "test_status": "PASS",
        "disposition": "SUPERSEDED_BY_MAIN",
    },
    {
        "refs": ["origin/agent/private-predecessor-capability-migration-v1"],
        "head": "459fb45",
        "focused_tests": 14,
        "test_status": "PASS",
        "disposition": "SUPERSEDED_BY_MAIN",
    },
    {
        "refs": ["origin/agent/staged-live-limited"],
        "head": "a71af92",
        "focused_tests": 4,
        "test_status": "PASS",
        "disposition": "SUPERSEDED_BY_FINAL_PRICE_BRANCH",
    },
    {
        "refs": ["origin/codex/checkpoint-v2-alternate-preservation-20260828"],
        "head": "a957f9c",
        "focused_tests": 34,
        "test_status": "PASS",
        "disposition": "EXCLUDED_ALTERNATE_CHECKPOINT_DESIGN",
    },
    {
        "refs": ["origin/codex/ku-bo-readiness-live-canary-v1"],
        "head": "630f929",
        "focused_tests": 49,
        "test_status": "PASS",
        "disposition": "EXCLUDED_CANARY_WITHOUT_LIVE_RUNTIME",
    },
    {
        "refs": [
            "origin/codex/kuwait-hybrid-full-market-collection-v1",
            "origin/codex/one-security-checkpoint-v2",
        ],
        "head": "eb7a81f",
        "focused_tests": 56,
        "test_status": "PASS",
        "disposition": "EXCLUDED_CHECKPOINT_WITHOUT_LIVE_RUNTIME",
        "reason": "two branch refs point to the same head",
    },
)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _module_disposition(name: str) -> tuple[str, str]:
    if name in MIGRATED_MODULES:
        return "MIGRATED", "direct tests pass in the clean repository"
    if name in REPLACED_MODULES:
        return "REPLACED", "the legacy entrypoint was replaced by the bounded clean CLI"
    if name in {"synthetic", "synthetic_network"}:
        return "EXCLUDED_SYNTHETIC_ONLY", "fixtures are tests, not runtime capability"
    if any(
        token in name
        for token in (
            "source",
            "ingestion",
            "connector",
            "capture",
            "live",
            "network",
            "parser_materialization",
        )
    ):
        return "EXCLUDED_NO_LIVE_SOURCE_EVIDENCE", "legacy inventory reports zero LIVE_OPERATIONAL sources"
    if any(
        token in name
        for token in (
            "automation",
            "recovery",
            "priority",
            "champion",
            "codex",
            "backfill",
            "admission",
            "workspace",
            "bootstrap",
        )
    ):
        return "EXCLUDED_OPERATIONAL_OVERHEAD", "control layer is not required by the accepted local runtime"
    if any(
        token in name
        for token in (
            "evaluation",
            "modelcard",
            "rank",
            "replay",
            "decision",
            "execution",
            "pipeline",
            "ledger",
            "outcome_sessions",
            "stopgates",
            "pack",
        )
    ):
        return "EXCLUDED_UNVALIDATED_PREDICTIVE_PATH", "no real point-in-time performance evidence supports this path"
    return "EXCLUDED_LEGACY_SCOPE", "not required by the accepted evidence-bound local analysis path"


def _file_disposition(path: str, new_root: Path) -> tuple[str, str]:
    candidate = new_root / path
    if path.startswith("src/kubo/") and path.endswith(".py"):
        return _module_disposition(Path(path).stem)
    if path == "tests/test_provenance.py":
        return "MIGRATED_PARTIAL", "pipeline-coupled test removed; six core provenance tests retained"
    if path.startswith("tests/"):
        return (
            ("MIGRATED", "test retained in clean suite")
            if candidate.is_file()
            else ("EXCLUDED_WITH_LEGACY_COMPONENT", "test targets an excluded component or fixture")
        )
    if path.startswith("schemas/"):
        return (
            ("MIGRATED", "schema belongs to an accepted component")
            if candidate.is_file()
            else ("EXCLUDED_WITH_LEGACY_COMPONENT", "schema belongs to an excluded legacy contract")
        )
    if path.startswith("config/"):
        return "EXCLUDED_LEGACY_RUNTIME_CONFIG", "clean core has no network or scheduled runtime configuration"
    if path.startswith(".github/workflows/"):
        return "REPLACED", "legacy operational workflows replaced by one bounded CI workflow"
    if path.startswith("scripts/"):
        return "EXCLUDED_OPERATIONAL_SCRIPT", "legacy control script is outside the accepted runtime"
    if path.startswith("docs/"):
        return "EXCLUDED_HISTORICAL_DOCUMENT", "legacy status and handoff documents are not runtime truth"
    if path.startswith(("examples/", "research/", "workouts/", "artifacts/", ".agents/")):
        return "EXCLUDED_NON_RUNTIME_ARTIFACT", "fixture, research note, workout, artifact, or legacy skill"
    if path in {"LICENSE", "SECURITY.md"} and candidate.is_file():
        return "MIGRATED", "root policy retained"
    if path in {"README.md", "pyproject.toml", ".gitignore"}:
        return "REPLACED", "root metadata rebuilt for the clean repository"
    return "EXCLUDED_LEGACY_ROOT", "legacy repository-control file is not part of the clean runtime"


def build_audit(legacy_root: Path, new_root: Path) -> dict[str, Any]:
    legacy_root = legacy_root.resolve()
    new_root = new_root.resolve()
    head = _git(legacy_root, "rev-parse", "HEAD")
    if head != SOURCE_SHA:
        raise ValueError(f"legacy HEAD mismatch: expected {SOURCE_SHA}, got {head}")
    tracked = [item for item in _git(legacy_root, "ls-files").splitlines() if item]
    rows = []
    counts: dict[str, int] = {}
    for path in tracked:
        disposition, reason = _file_disposition(path, new_root)
        rows.append({"path": path, "disposition": disposition, "reason": reason})
        counts[disposition] = counts.get(disposition, 0) + 1
    return {
        "schema_version": "1.0",
        "legacy_repository": "mohsamir7122/ku-bo",
        "legacy_head": head,
        "tracked_file_count": len(tracked),
        "component_audit_complete": True,
        "baseline": {
            "tests_run": 2512,
            "tests_passed": 2512,
            "compileall": "PASS",
            "smoke_check": "PASS",
            "secret_guard": "PASS",
            "live_operational_sources": 0,
            "fixture_only_end_to_end_sources": 2,
            "defined_only_sources": 69,
            "broad_exception_handlers": 7,
        },
        "disposition_counts": dict(sorted(counts.items())),
        "branches": list(BRANCH_AUDIT),
        "files": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-root", required=True, type=Path)
    parser.add_argument("--new-root", default=Path.cwd(), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = build_audit(arguments.legacy_root, arguments.new_root)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
