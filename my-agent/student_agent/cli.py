"""Command-line entry point for the student agent."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .agent import run_agent
from .approval import terminal_approve
from .model import OllamaModel
from .runtime import Runtime

DEFAULT_TRACE_DIR = Path(__file__).resolve().parents[1] / "traces"
MAX_SHOWN_CHARS = 300


def build_parser():
    parser = argparse.ArgumentParser(description="Run the Week 1 coding agent")
    parser.add_argument("--root", required=True, help="target workspace")
    parser.add_argument(
        "--mode",
        choices=("read-only", "edit"),
        default="read-only",
    )
    parser.add_argument("--tools", help="comma-separated enabled tools (default: all)")
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
    )
    parser.add_argument("--offline", action="store_true", help="serve docs from labelled local fixtures")
    parser.add_argument("--offline-fixture", help="with --offline: file served for the decimal docs URL")
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--trace", help="JSONL event log outside the target (default: my-agent/traces/)")
    parser.add_argument(
        "--without-injection-guidance",
        action="store_true",
        help="baseline for the injection experiment: no untrusted-data guidance or labels",
    )
    parser.add_argument("--task", required=True)
    return parser


def _clip(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_SHOWN_CHARS else text[:MAX_SHOWN_CHARS] + " ..."


def show(event):
    """Print a short, human-readable line for each observable event."""
    kind = event["event"]
    if kind == "request":
        action = event["action"]
        print(f"[turn {event['turn']}] {action['tool']} {_clip(action['args'])}", file=sys.stderr)
    elif kind == "result":
        result = event["result"]
        if event.get("tool") is None:
            print(f"[turn {event['turn']}] invalid reply: {_clip(event.get('raw', ''))}", file=sys.stderr)
        print(f"    -> {result['status']}: {_clip(result['output'])}", file=sys.stderr)


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"--root {args.root} is not a directory")
    if args.offline_fixture and not args.offline:
        parser.error("--offline-fixture requires --offline")
    if args.max_turns < 1:
        parser.error("--max-turns must be at least 1")
    enabled = None if args.tools is None else {name.strip() for name in args.tools.split(",") if name.strip()}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    trace_path = Path(args.trace or DEFAULT_TRACE_DIR / f"run-{stamp}.jsonl").resolve()
    if _inside(trace_path, root):
        parser.error("--trace must be outside the target workspace")
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        runtime = Runtime(
            root,
            mode=args.mode,
            enabled=enabled,
            # `emit` is defined below, once the trace file is open.
            approve=lambda command, cwd: terminal_approve(command, cwd, log=emit),
            offline=args.offline,
            offline_fixture=args.offline_fixture,
        )
    except ValueError as exc:
        parser.error(str(exc))

    with open(trace_path, "a", encoding="utf-8") as trace:

        def emit(event):
            event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
            trace.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            trace.flush()
            show(event)

        tools = [tool["name"] for tool in runtime.describe_tools()]
        emit({
            "event": "start", "root": str(root), "mode": args.mode, "tools": tools, "model": args.model,
            "offline": args.offline, "offline_fixture": args.offline_fixture,
            "injection_guidance": not args.without_injection_guidance, "task": args.task,
        })
        print(f"model {args.model} | {args.mode} | tools: {', '.join(tools) or 'none'}", file=sys.stderr)
        print(f"trace: {trace_path}", file=sys.stderr)
        result = run_agent(
            OllamaModel(args.model),
            runtime,
            args.task,
            max_turns=args.max_turns,
            emit=emit,
            injection_guidance=not args.without_injection_guidance,
        )

    print(f"\nTermination: {result['termination']} after {result['turns']} turn(s) ({result['reason']})")
    if result["final"]:
        print(f"Model's final claim (unverified):\n{result['final']}")
    return 0 if result["termination"] == "final" else 1


if __name__ == "__main__":
    raise SystemExit(main())
