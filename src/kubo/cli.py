from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import __version__
from .ca_adjustments import formula_self_check
from .local_analysis import write_local_analysis


CORE_CAPABILITIES = (
    "atomic_output",
    "corporate_action_adjustments",
    "descriptive_analyst_signals",
    "effective_dated_identity",
    "evidence_hashing",
    "liquidity_constraints",
    "local_evidence_bundle_analysis",
    "official_data_parsing",
    "outcome_evidence_validation",
    "point_in_time_event_features",
    "portfolio_state_validation",
    "research_price_history_validation",
    "runtime_trust_verification",
    "source_resilience_policy",
    "trading_status_history",
    "temporal_leakage_guards",
)


def build_self_check() -> dict[str, object]:
    corporate_actions = formula_self_check()
    status = "PASS" if corporate_actions.get("status") == "PASS" else "BLOCKED"
    return {
        "status": status,
        "version": __version__,
        "stage": "CLEAN_CORE",
        "capabilities": list(CORE_CAPABILITIES),
        "claim_boundaries": {
            "live_collection": False,
            "live_trading": False,
            "prediction": False,
            "recommendation": False,
        },
        "checks": {"corporate_action_formulas": corporate_actions},
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="kubo-core")
    subcommands = root.add_subparsers(dest="command", required=True)
    subcommands.add_parser("self-check", help="validate the migrated clean core")
    local = subcommands.add_parser(
        "analyze-local",
        help="analyze a verified local evidence bundle without network access",
    )
    local.add_argument("--bundle", required=True, type=Path)
    local.add_argument("--output", required=True, type=Path)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command == "self-check":
        report = build_self_check()
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["status"] == "PASS" else 1
    if arguments.command == "analyze-local":
        try:
            report = write_local_analysis(arguments.bundle, arguments.output)
        except (OSError, RuntimeError, ValueError) as exc:
            print(
                json.dumps(
                    {"status": "BLOCKED", "error": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2
