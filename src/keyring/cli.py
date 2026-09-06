from __future__ import annotations

import argparse
import json

from .classifier import classify_log
from .config import load_probe_config, load_strategy_config
from .dashboard import serve
from .evidence import EvidenceLog
from .reach import least_privilege_diff
from .agentic import AgenticSession, capture_tools_list


def main() -> int:
    parser = argparse.ArgumentParser(prog="keyring")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config")
    validate.add_argument("--probes", default="config/probes.yaml")
    validate.add_argument("--strategy", default="config/strategy.yaml")

    classify = subparsers.add_parser("classify")
    classify.add_argument("--evidence", default="evidence/raw/0001-m0-preflight.jsonl")
    classify.add_argument("--strategy", default="config/strategy.yaml")

    dashboard = subparsers.add_parser("dashboard")
    dashboard.add_argument("--evidence", default="evidence/raw/0001-m0-preflight.jsonl")
    dashboard.add_argument("--strategy", default="config/strategy.yaml")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8080)

    leastpriv = subparsers.add_parser(
        "least-privilege", help="diff the strategy manifest against the measured fingerprint"
    )
    leastpriv.add_argument("--strategy", default="config/strategy.yaml")
    leastpriv.add_argument("--evidence-dir", default="evidence/raw")
    leastpriv.add_argument("--json", action="store_true")

    authority = subparsers.add_parser(
        "authority", help="regenerate the effective authority map from the evidence log alone"
    )
    authority.add_argument("--evidence-dir", default="evidence/raw")
    authority.add_argument("--json", action="store_true")

    capture = subparsers.add_parser("capture-tools", help="capture tools/list using session values from the environment")
    capture.add_argument("--evidence", default="evidence/raw/runtime.jsonl")
    capture.add_argument("--run-id")

    args = parser.parse_args()
    if args.command == "least-privilege":
        from .leastprivilege import diff as lp_diff, render as lp_render

        result = lp_diff(args.strategy, args.evidence_dir)
        print(json.dumps(result, indent=2) if args.json else lp_render(result))
        return 0
    if args.command == "authority":
        from .authority import derive, render

        result = derive(args.evidence_dir)
        print(json.dumps(result, indent=2) if args.json else render(result))
        return 0
    if args.command == "validate-config":
        probes = load_probe_config(args.probes)
        strategy = load_strategy_config(args.strategy)
        print(
            json.dumps(
                {
                    "probes": {"path": str(probes.path), "sha256": probes.sha256},
                    "strategy": {"path": str(strategy.path), "sha256": strategy.sha256},
                },
                indent=2,
            )
        )
        return 0
    if args.command == "classify":
        log = EvidenceLog(args.evidence)
        config = load_probe_config().model
        classifications = classify_log(log, [definition.id for definition in config.capabilities])
        strategy = load_strategy_config(args.strategy).model
        print(
            json.dumps(
                {
                    "classifications": [item.model_dump(mode="json") for item in classifications],
                    "strategy_diff": least_privilege_diff(strategy, classifications),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "dashboard":
        serve(args.evidence, host=args.host, port=args.port, strategy_path=args.strategy)
        return 0
    if args.command == "capture-tools":
        record = capture_tools_list(AgenticSession.from_environment(), EvidenceLog(args.evidence), run_id=args.run_id)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return 0
    return 2
