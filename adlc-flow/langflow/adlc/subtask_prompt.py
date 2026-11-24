"""Prompt template that asks the DSH LLM to divide a task into subtasks.

This is used for on-demand subtask generation: after the user accepts
the high-level plan, the system SDKs to DSH for each task and asks
"how would you divide this task into parallel subtasks?".

The prompt is intentionally focused on a single task so the LLM can
tailor the subtask structure to the task's specific content.
"""

from __future__ import annotations

from textwrap import dedent

SUBTASK_GENERATION_PROMPT = dedent(
    """
    You are the ADLC subtask planner. Given a single task from an
    approved execution plan, design a set of parallel subtasks that
    will accomplish the task efficiently.

    ## Context

    The task is part of a larger workflow. Other tasks may have already
    completed or will run after this one. Focus ONLY on dividing THIS
    task into subtasks — do not propose changes to other tasks.

    ## Your goal

    Divide the task into **2 to 5 concrete subtasks** that can be
    executed by an AI coding agent. The number of subtasks should
    reflect the task's actual size and complexity:

    - **Small / trivial task** (e.g. "rename a variable", "add a log
      line", "update one config"): 1 subtask is acceptable as a last
      resort, but prefer 2 if there is any meaningful split.
    - **Medium task** (e.g. "implement a feature module", "write tests
      for a service", "design a schema"): 2–4 subtasks.
    - **Large task** (e.g. "build the entire backend", "design the
      full system architecture", "implement end-to-end auth flow"):
      4–5 subtasks.

    Avoid producing a single subtask unless the work is genuinely
    atomic. A single subtask defeats the purpose of parallel
    execution.

    ## Parallelism and dependencies

    Maximize parallelism. Subtasks that do not depend on each other
    MUST have an empty ``dependencies`` array so they can run in
    parallel.

    Only add a dependency when one subtask genuinely cannot start
    until another finishes (e.g. "write the API spec" must finish
    before "implement the API client"). Do NOT add dependencies for
    vague logical ordering — if both can start immediately, leave
    ``dependencies`` empty.

    Typical patterns:
    - **Fully parallel**: all subtasks have ``dependencies: []``.
    - **Parallel + finalizer**: N parallel subtasks feed into one
      final subtask that aggregates their results.
    - **Pipeline**: a small chain where each step depends on the
      previous one (use sparingly — pipelines serialize execution).

    ## Output schema

    ```json
    {{
      "schema_version": "0.1",
      "task_id": "{task_id}",
      "task_name": "{task_name}",
      "subtasks": [
        {{
          "id": "{task_id}.sub-1",
          "name": "<short title specific to this subtask's work>",
          "description": "<what this subtask accomplishes>",
          "objective": "<prompt that will be sent to the agent for this subtask — at least 50 characters, specific and actionable>",
          "dependencies": [],
          "trigger": "on_success",
          "timeout_seconds": 300,
          "expected_outputs": ["summary", "diff"]
        }}
      ]
    }}
    ```

    ## Rules

    1. Produce **2 to 5 subtasks** for normal tasks. 1 subtask is
       allowed only when the task is genuinely atomic (rare).
    2. Each subtask should take roughly 2–15 minutes of agent work.
       Do NOT split a 30-second job into 5 subtasks.
    3. Subtasks must be **TAILORED** to this task's specific content —
       do NOT use a generic template. Read the task description and
       objective carefully and name each subtask after the concrete
       work it does.
    4. Maximize parallelism: subtasks with no real ordering constraint
       MUST have ``dependencies: []``.
    5. Use ``trigger`` to express failure handling:
       - ``on_success`` (default): run only if the dependency succeeded.
       - ``on_failure``: run only if the dependency failed.
       - ``on_completed``: run regardless of outcome.
    6. IDs must match ``^[a-z0-9][a-z0-9._-]*$``. Use hierarchical IDs
       like ``{task_id}.sub-1``, ``{task_id}.sub-2``, etc.
    7. The subtask graph MUST be acyclic.
    8. Each ``objective`` must be at least 50 characters and describe
       a concrete, actionable piece of work — not a vague summary.
    9. Do NOT include secrets, credentials, or PII in any field.
    10. Output ONLY the JSON object wrapped in a single ```json fence.
        No prose before or after.

    ## Task to divide

    **Name**: {task_name}
    **Type**: {task_type}
    **Description**: {task_description}
    **Objective**: {task_objective}

    ## Workflow context

    {workflow_context}
    """
).strip()


def render_subtask_prompt(
    task_id: str,
    task_name: str,
    task_type: str,
    task_description: str,
    task_objective: str,
    workflow_context: str = "",
) -> str:
    """Render the subtask-generation prompt for a given task."""
    return SUBTASK_GENERATION_PROMPT.format(
        task_id=task_id,
        task_name=task_name,
        task_type=task_type,
        task_description=task_description or "(no description)",
        task_objective=task_objective or "(no objective)",
        workflow_context=workflow_context or "(no additional context)",
    ).strip()


__all__ = ["SUBTASK_GENERATION_PROMPT", "render_subtask_prompt"]
