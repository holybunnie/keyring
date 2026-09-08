from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .classifier import classify_log
from .config import load_probe_config, load_strategy_config
from .dashboard import serve
from .evidence import EvidenceLog
from .reach import least_privilege_diff
from .agentic import AgenticSession, capture_tools_list
from .model_client import TextModel


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
    dashboard.add_argument("--evidence", default="evidence/raw")
    dashboard.add_argument("--strategy", default="config/strategy.yaml")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8080)
    dashboard.add_argument(
        "--state-file",
        help="serve a previously verified dashboard state snapshot without rereading evidence",
    )

    freach = subparsers.add_parser(
        "financial-reach", help="layered capital view derived from the evidence log"
    )
    freach.add_argument("--evidence-dir", default="evidence/raw")
    freach.add_argument("--json", action="store_true")

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

    plan = subparsers.add_parser(
        "plan-probe",
        help="propose and deterministically validate one non-executing probe",
    )
    plan.add_argument("--tool-schema", required=True, help="JSON file containing one discovered tool schema")
    plan.add_argument("--filters", required=True, help="JSON file containing live symbol filters")
    plan.add_argument("--capability", required=True)
    plan.add_argument("--symbol", required=True)
    plan.add_argument("--tool-name")
    plan.add_argument("--discovered-tools", help="JSON file containing discovered tool names")
    plan.add_argument("--history", help="JSON file containing prior probe records")
    plan.add_argument("--model-assisted", action="store_true", help="use the explicitly configured Claude model")
    plan.add_argument(
        "--claude-code",
        action="store_true",
        help="use the logged-in Claude Code CLI as the text-only model",
    )
    plan.add_argument("--max-attempts", type=int, default=2)

    agent_replay = subparsers.add_parser(
        "agent-replay",
        help="reconstruct a recorded agent run from verified retained evidence",
    )
    agent_replay.add_argument("--evidence-dir", default="evidence/raw")
    agent_replay.add_argument(
        "--ref",
        help="recorded model-planned probe as FILE#SEQUENCE (default: retained 0012#78)",
    )
    agent_replay.add_argument("--json", action="store_true")

    interpret = subparsers.add_parser(
        "interpret-response",
        help="deterministically classify a response and optionally record Claude's interpretation",
    )
    interpret.add_argument("--response", required=True, help="raw response file, or - for stdin")
    interpret.add_argument("--error-code")
    interpret.add_argument("--outcome")
    interpret.add_argument("--context", help="JSON file containing interpretation context")
    interpret.add_argument("--model-assisted", action="store_true", help="use the explicitly configured Claude model")
    interpret.add_argument(
        "--claude-code",
        action="store_true",
        help="use the logged-in Claude Code CLI as the text-only model",
    )

    trace_cmd = subparsers.add_parser("trace", help="rebuild evidence-backed permission traces")
    trace_cmd.add_argument("--evidence-dir", default="evidence/raw")
    trace_cmd.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "financial-reach":
        from .financialreach import reach as fr_reach, render as fr_render

        result = fr_reach(args.evidence_dir)
        print(json.dumps(result, indent=2, default=str) if args.json else fr_render(result))
        return 0
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
        strategy_config = load_strategy_config(args.strategy)
        print(
            json.dumps(
                {
                    "probes": {"path": str(probes.path), "sha256": probes.sha256},
                    "strategy": {
                        "path": str(strategy_config.path),
                        "sha256": strategy_config.sha256,
                    },
                },
                indent=2,
            )
        )
        return 0
    if args.command == "classify":
        log = EvidenceLog(args.evidence)
        config = load_probe_config().model
        classifications = classify_log(log, [definition.id for definition in config.capabilities])
        strategy_model = load_strategy_config(args.strategy).model
        print(
            json.dumps(
                {
                    "classifications": [item.model_dump(mode="json") for item in classifications],
                    "strategy_diff": least_privilege_diff(
                        strategy_model, classifications
                    ),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "dashboard":
        serve(
            args.evidence,
            host=args.host,
            port=args.port,
            strategy_path=args.strategy,
            state_file=args.state_file,
        )
        return 0
    if args.command == "capture-tools":
        record = capture_tools_list(AgenticSession.from_environment(), EvidenceLog(args.evidence), run_id=args.run_id)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return 0
    if args.command == "plan-probe":
        from .agent import KeyringAgent
        from .model_client import ClaudeCodeModel, ClaudeMessagesModel

        def load_json(path: str) -> object:
            text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
            return json.loads(text)

        tool_schema = load_json(args.tool_schema)
        filters = load_json(args.filters)
        discovered = load_json(args.discovered_tools) if args.discovered_tools else None
        history = load_json(args.history) if args.history else []
        if not isinstance(tool_schema, dict):
            raise ValueError("--tool-schema must contain a JSON object")
        if discovered is not None and isinstance(discovered, dict):
            discovered = discovered.get("tools", [])
        if discovered is not None and not isinstance(discovered, list):
            raise ValueError("--discovered-tools must contain a JSON list")
        if not isinstance(history, list):
            raise ValueError("--history must contain a JSON list")
        if args.model_assisted and args.claude_code:
            parser.error("choose one of --model-assisted or --claude-code")
        model: TextModel | None = None
        if args.claude_code:
            model = ClaudeCodeModel(model=os.environ.get("KEYRING_MODEL", "haiku"))
        elif args.model_assisted:
            model = ClaudeMessagesModel.from_environment()
        try:
            planned = KeyringAgent(model, max_attempts=args.max_attempts).plan_probe(
                capability=args.capability,
                tool_schema=tool_schema,
                tool_name=args.tool_name,
                symbol=args.symbol,
                filters=filters,
                discovered_tool_names=discovered,
                history=history,
            )
            print(json.dumps(planned.as_dict(), indent=2, default=str))
        finally:
            if model is not None:
                model.close()
        return 0
    if args.command == "agent-replay":
        from .agent_replay import render, replay

        result = replay(args.evidence_dir, source_ref=args.ref)
        print(json.dumps(result, indent=2, default=str) if args.json else render(result))
        return 0
    if args.command == "interpret-response":
        from .interpreter import ResponseInterpreter
        from .model_client import ClaudeCodeModel, ClaudeMessagesModel

        raw_response = (
            sys.stdin.read()
            if args.response == "-"
            else Path(args.response).read_text(encoding="utf-8")
        )
        context = {}
        if args.context:
            context_value = json.loads(Path(args.context).read_text(encoding="utf-8"))
            if not isinstance(context_value, dict):
                raise ValueError("--context must contain a JSON object")
            context = context_value
        if args.model_assisted and args.claude_code:
            parser.error("choose one of --model-assisted or --claude-code")
        model = None
        if args.claude_code:
            model = ClaudeCodeModel(model=os.environ.get("KEYRING_MODEL", "haiku"))
        elif args.model_assisted:
            model = ClaudeMessagesModel.from_environment()
        try:
            interpretation = ResponseInterpreter(model).interpret(
                raw_response=raw_response,
                error_code=args.error_code,
                outcome=args.outcome,
                context=context,
            )
            print(json.dumps(interpretation.as_dict(), indent=2))
        finally:
            if model is not None:
                model.close()
        return 0
    if args.command == "trace":
        from .trace import render, trace

        result = trace(args.evidence_dir)
        print(json.dumps(result, indent=2, default=str) if args.json else render(result))
        return 0
    return 2
