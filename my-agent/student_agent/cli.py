"""Command-line entry point for the student agent."""

import argparse
import os


def build_parser():
    parser = argparse.ArgumentParser(description="Run the Week 1 coding agent")
    parser.add_argument("--root", required=True, help="target workspace")
    parser.add_argument(
        "--mode",
        choices=("read-only", "edit"),
        default="read-only",
    )
    parser.add_argument("--tools", help="comma-separated enabled tools")
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--task", required=True)
    return parser


def main():
    args = build_parser().parse_args()
    # TODO Checkpoint 4: connect OllamaModel, Runtime, approval, and run_agent.
    raise NotImplementedError(f"Connect the CLI for {args.model}")


if __name__ == "__main__":
    main()
