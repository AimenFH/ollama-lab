"""Bounded action-observation loop."""


def run_agent(model, runtime, task, max_turns=15, emit=None):
    """Run the model and tools until a defined termination condition.

    `model(messages)` returns one JSON string. `runtime.execute(action)` returns
    one result dictionary. The handout defines the protocol, emitted events, and
    required termination values.
    """
    # TODO Checkpoint 2: implement the bounded action-observation loop.
    raise NotImplementedError("Complete the action-observation loop")
