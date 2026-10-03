# Week 1 coding agent

A small Python coding agent that drives a local Ollama model through an
action-observation loop. The model proposes one JSON action per turn, and the
Python runtime decides whether that action may run. The agent uses only the
Python standard library.

## Setup

Requirements: Python 3.10+, Git, bash, and Ollama (macOS, Linux, or WSL2).

```bash
ollama pull qwen2.5-coder:7b
ollama run qwen2.5-coder:7b "Reply with READY"
```

## Model selection

The loop does not hardcode a model. Choose one with `--model` or set
`OLLAMA_MODEL`; if neither is given, the agent uses `qwen2.5-coder:7b`.

```bash
export OLLAMA_MODEL=qwen2.5-coder:3b   # lower-memory option
```

Requests go to `http://127.0.0.1:11434/api/chat` with `format: "json"`,
temperature 0, a 2048-token output limit, a 16384-token context, a 90-second
timeout, and a 1 MB response cap. The adapter bypasses any configured proxy,
so conversation content stays on the machine.

## Running

Run from the package directory (the folder containing `my-agent` and
`target-service`):

```bash
cd my-agent
python3 -m student_agent --root ../target-service --mode read-only --offline \
  --task "Inspect the order service and docs/business-rules.md. ..."
```

| Option | Meaning |
|---|---|
| `--root` | Target workspace (required) |
| `--mode` | `read-only` (default) or `edit` |
| `--tools` | Comma-separated tool list; default is all tools |
| `--model` | Ollama model name; default `$OLLAMA_MODEL` |
| `--offline` | Serve the Decimal docs URL from `fixtures/decimal-offline.txt`, labelled "offline fixture" |
| `--offline-fixture` | With `--offline`: serve a different fixture (e.g. `fixtures/web-injected.txt`) |
| `--max-turns` | Turn limit, default 15 |
| `--trace` | JSONL trace path; must be outside the target. Default `my-agent/traces/run-<timestamp>.jsonl` |
| `--without-injection-guidance` | Baseline for the injection experiment: removes the untrusted-data guidance and labels |
| `--task` | Task text (required) |

The exit code is 0 only when the model returns a final response. A run ends
with one of four terminations: `final`, `turn_limit`, `model_error`, or
`cancelled` (Ctrl+C). The CLI prints the model's final message as an
unverified claim.

## Tests and checks

```bash
cd my-agent && python3 -m unittest discover -s tests -v
cd .. && python3 checks/check_agent.py --implementation my-agent --module student_agent
cd target-service && python3 -m unittest discover -s tests -v
```

The agent tests use fake models, so they run without Ollama.

## Permissions

| Capability | read-only | edit |
|---|---|---|
| `list_files`, `read_file`, `search_files` | allowed if enabled | allowed if enabled |
| `fetch_url` | allowed if enabled | allowed if enabled |
| `write_file`, `edit_file` | denied | allowed inside the workspace |
| `bash` | denied before any prompt | human approval for every command |

The model only sees tools allowed by both `--mode` and `--tools`. The runtime
checks both settings again at dispatch, so a tool the model was never shown is
still denied if it asks for one.

### File boundaries

Paths are resolved against the root. The runtime rejects absolute paths, `..`,
symlinks that resolve outside the root, and hidden paths such as `.git` and
`.venv`. Listing does not follow links. The course-owned files
`orders/validation.py`, `tests/test_acceptance.py`, and
`docs/business-rules.md` can be read but never written. Reads stop at 12,000
characters and say when they were truncated. Search scans at most 200 files
and returns at most 50 matches. `write_file` refuses to overwrite an existing
file, and `edit_file` requires `old` to occur exactly once in a file of at
most 12,000 bytes.

### Bash approval

Before anything runs, the agent prints the full command and working directory,
with non-printable characters shown escaped, then asks
`Approve this command only? Type yes:`. Only the exact answer `yes` approves.
Empty input, EOF, or any other answer denies, and every decision is logged.
Approved commands run as `/bin/bash --noprofile --norc -c` in the target
directory with stdin closed and a minimal environment (only `PATH`, `HOME`,
`LANG`, and `TMPDIR`, so API keys are not passed on). Each command has a
20-second timeout and a 12,000-byte output cap. On timeout, excess output, or
cancellation, the agent kills the whole process group.

### Documentation fetch

`fetch_url` makes HTTPS GET requests to `docs.python.org` on the default port
or 443. URLs with credentials, a query, a fragment, or unusual path characters
are rejected. Redirects are refused, only text or HTML is accepted, the
timeout is 10 seconds, and at most 12,000 bytes are read, with truncation
reported. Offline mode applies the same URL validation.

### Prompt-injection defense

The system prompt tells the model that files, tool results, and fetched pages
are data and cannot give it instructions. Every observation is wrapped as a
`tool_result` labelled untrusted. Errors and denials go back to the model as
ordinary observations; nothing from a tool is ever added as a system message.

## Limitations and unfinished behavior

- With the full edit-mode task, `qwen2.5-coder:7b` did not repair the pricing
  by itself. It kept toggling the `validate_order` call, and its test commands
  were denied. The final repair came from several short runs, each focused on
  one rule with only `read_file` and `edit_file` enabled, and a separate run
  added the regression test.
- Prompt guidance alone did not stop the file injection. With guidance
  enabled, the model still asked to edit `orders/validation.py` and repeated
  the injected "passed all checks" claim. The runtime's protected-file check
  blocked the edit. In the web variant the guidance helped, and the model
  declined to follow the injected instructions.
- Bash is not a sandbox. An approved command can read or write outside the
  target and bypass every file-tool rule, including the protected files.
  Approval only works if the person reading the command catches the problem.
- The model's final message is a claim. Check it with `git diff`, the test
  suite, and `git status` in the target.
- Fetched HTML is reduced to text and capped at 12,000 bytes, so the model
  never sees a full documentation page.
- Traces contain file contents and model output. They are stored outside the
  target and are git-ignored.
