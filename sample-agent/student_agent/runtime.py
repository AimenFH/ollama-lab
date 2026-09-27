"""Tool registry and permission boundary."""

from pathlib import Path


TOOL_ARGUMENTS = {
    "list_files": (),
    "read_file": ("path",),
    "search_files": ("query",),
    "write_file": ("path", "content"),
    "edit_file": ("path", "old", "new"),
    "fetch_url": ("url",),
    "bash": ("command",),
}


class Runtime:
    """Validate and execute model-requested tools inside a workspace."""

    def __init__(
        self,
        root,
        mode="read-only",
        enabled=None,
        approve=None,
        offline=False,
    ):
        self.root = Path(root).resolve()
        self.mode = mode
        self.enabled = set(TOOL_ARGUMENTS if enabled is None else enabled)
        self.approve = approve or (lambda _command, _cwd: False)
        self.offline = offline

    def execute(self, action):
        """Validate one action, enforce policy, and return a result object."""
        # TODO Checkpoint 3: validate, authorize, and dispatch the action.
        raise NotImplementedError("Complete the runtime dispatcher and tools")
