# Sample agent scaffold

This optional scaffold standardizes the public interface and file layout used
by the Week 1 checks. Copy it to `my-agent` before working on the lab:

```bash
cp -R sample-agent my-agent
```

The scaffold is intentionally incomplete. It supplies names, module boundaries,
CLI arguments, and fake-model test cases. Students still implement the assessed
action-observation loop, Ollama request, tools, permission checks, bash approval,
and prompt-injection defenses.

Suggested order:

1. Complete the loop in `student_agent/agent.py` and make the included tests pass.
2. Complete the registry and tools in `student_agent/runtime.py`.
3. Complete the local Ollama request in `student_agent/model.py`.
4. Connect the components in `student_agent/cli.py`.
5. Run the supplied public checks from the lab package directory.

```bash
cd sample-agent
python3 -m unittest discover -s tests -v
cd ..
python3 checks/check_agent.py --implementation my-agent --module student_agent
```

The untouched sample is expected to fail because the core methods raise
`NotImplementedError`.
