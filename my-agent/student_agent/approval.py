"""Human approval for bash commands. Only the person at the terminal answers."""

import sys

PROMPT = "Approve this command only? Type yes: "


def terminal_approve(command, cwd, read=input, write=None, log=None):
    """Show the full command and working directory; approve only on exactly `yes`."""
    write = write or (lambda text: print(text, file=sys.stderr))
    write("\nThe agent wants to run a bash command.")
    write(f"Command:           {command}")
    if not command.isprintable():
        # Newlines, carriage returns, or escape codes can hide part of a command.
        write(f"Exact characters:  {command!r}")
    write(f"Working directory: {cwd}")
    try:
        answer = read(PROMPT)
    except EOFError:
        answer = None
    approved = answer == "yes"
    if log:
        log({"event": "approval", "command": command, "cwd": cwd, "approved": approved})
    write("Approved." if approved else "Denied.")
    return approved
