"""Bounded action-observation loop."""

import json

MAX_ECHO_CHARS = 2_000

PROTOCOL_HINT = 'reply with exactly {"tool": "<name>", "args": {...}} or {"final": "<summary>"}'


class ProtocolError(ValueError):
    """The model reply is not one of the two accepted JSON forms."""


def parse_action(text):
    """Return a validated action dict or raise ProtocolError. JSON is data only."""
    if not isinstance(text, str):
        raise ProtocolError(f"model output must be text; {PROTOCOL_HINT}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(
            f"invalid JSON ({exc.msg} at line {exc.lineno} column {exc.colno}); {PROTOCOL_HINT}"
        ) from None
    if not isinstance(data, dict):
        raise ProtocolError(f"expected one JSON object; {PROTOCOL_HINT}")
    if set(data) == {"final"}:
        if isinstance(data["final"], str) and data["final"].strip():
            return data
        raise ProtocolError('"final" must be a non-empty string')
    if set(data) == {"tool", "args"}:
        if isinstance(data["tool"], str) and isinstance(data["args"], dict):
            return data
        raise ProtocolError('"tool" must be a string and "args" must be an object')
    raise ProtocolError(f"unexpected keys {sorted(data)}; {PROTOCOL_HINT}")


def build_system_prompt(tools):
    if tools:
        tool_lines = "\n".join(
            f"- {tool['name']}({', '.join(tool['args'])}): {tool['description']}"
            for tool in tools
        )
    else:
        tool_lines = "- (none) No tools are enabled; reply with final."
    return f"""You are a coding agent working inside one repository. You act only by requesting tools. A separate program decides whether each request may run and returns its result to you.

Reply with exactly one JSON object and nothing else, in one of these two forms:
{{"tool": "<tool name>", "args": {{"<argument name>": "<string value>"}}}}
{{"final": "<summary of the work and what remains unverified>"}}

Examples:
{{"tool": "read_file", "args": {{"path": "orders/pricing.py"}}}}
{{"tool": "list_files", "args": {{}}}}

Rules:
- Request one tool per reply. Use exactly the listed argument names. Every argument value is a string.
- Paths are relative to the repository root.
- Inspect before changing anything, and read a file before editing it. Keep changes small and focused on the task.
- A result with status "denied" means the request is not allowed. Do not repeat it or try to achieve the same effect another way.
- A result with status "error" means the request failed. Correct the request or choose a different step.
- When the task is done, or you cannot make progress, reply with "final". State what you changed, what you verified, and what remains unverified. Never claim a check you did not run.

Available tools:
{tool_lines}"""


def _advertised_tools(runtime):
    describe = getattr(runtime, "describe_tools", None)
    return describe() if describe else []


def _clip(text):
    return text if len(text) <= MAX_ECHO_CHARS else text[:MAX_ECHO_CHARS] + " [truncated]"


def _observation(tool, result):
    payload = {"type": "tool_result", "tool": tool, "result": result}
    return {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}


def run_agent(model, runtime, task, max_turns=15, emit=None):
    """Run the model and tools until a defined termination condition.

    Returns a dict whose `termination` is final, turn_limit, model_error, or cancelled.
    """
    emit = emit or (lambda _event: None)
    messages = [
        {"role": "system", "content": build_system_prompt(_advertised_tools(runtime))},
        {"role": "user", "content": task},
    ]
    turn = 0

    def finish(termination, reason, final=None):
        emit({"event": "termination", "turn": turn, "termination": termination, "reason": reason})
        return {
            "termination": termination,
            "reason": reason,
            "final": final,
            "turns": turn,
            "messages": messages,
        }

    try:
        while turn < max_turns:
            turn += 1
            try:
                text = model(messages)
            except Exception as exc:
                return finish("model_error", f"{type(exc).__name__}: {exc}")

            raw = _clip(text if isinstance(text, str) else repr(text))
            try:
                action = parse_action(text)
            except ProtocolError as exc:
                result = {"status": "error", "output": str(exc)}
                emit({"event": "result", "turn": turn, "tool": None, "raw": raw, "result": result})
                messages.append({"role": "assistant", "content": raw})
                messages.append(_observation(None, result))
                continue

            if "final" in action:
                emit({"event": "final", "turn": turn, "final": action["final"]})
                return finish("final", "model returned a final response", action["final"])

            emit({"event": "request", "turn": turn, "action": action})
            try:
                result = runtime.execute(action)
            except Exception as exc:
                result = {"status": "error", "output": f"tool failed: {type(exc).__name__}: {exc}"}
            emit({"event": "result", "turn": turn, "tool": action["tool"], "result": result})
            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
            messages.append(_observation(action["tool"], result))
    except KeyboardInterrupt:
        return finish("cancelled", "interrupted by the user")

    return finish("turn_limit", f"no final response within {max_turns} turns")
