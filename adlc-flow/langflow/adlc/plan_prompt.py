"""Prompt template that asks the DSH LLM to produce a structured plan.

The prompt is intentionally explicit about the JSON schema, the
granularity rules, and the trigger semantics so the LLM emits plans
that pass :func:`validate_plan` on the first try.
"""

from __future__ import annotations

from textwrap import dedent

PLAN_GENERATION_PROMPT = dedent(
    """
    You are the ADLC execution planner. Given a user request, design a
    parallel execution plan as a JSON object.

    ## Output schema

    ```json
    {{
      "schema_version": "0.1",
      "objective": "<one-line summary of the user's goal>",
      "description": "<optional longer description>",
      "tasks": [
        {{
          "id": "task-1",
          "name": "<short title>",
          "description": "<what this task accomplishes>",
          "objective": "<prompt that will be sent to the agent for this task>",
          "subtasks": [
            {{
              "id": "task-1.sub-1",
              "name": "<short title>",
              "description": "<what this subtask accomplishes>",
              "objective": "<prompt that will be sent to the agent for this subtask>",
              "dependencies": ["task-1.sub-0"],
              "trigger": "on_success",
              "timeout_seconds": 300,
              "expected_outputs": ["summary", "diff"]
            }}
          ],
          "dependencies": [],
          "aggregation": "collect"
        }}
      ]
    }}
    ```

    ## Rules

    1. Produce between 1 and 10 top-level tasks depending on complexity.
    2. Each task MUST contain at least one subtask. If a task is
       inherently atomic, give it a single subtask with no dependencies.
    3. Subtask granularity:
       - Each subtask should take roughly 2-15 minutes of agent work.
       - Do NOT split a subtask into smaller pieces unless the pieces
         can run in parallel.
       - Do NOT make a subtask so large that it spans multiple concerns.
    4. Dependencies express ordering. A subtask with no dependencies is
       eligible to run as soon as the plan starts.
    5. Use ``trigger`` to express failure handling:
       - ``on_success`` (default): run only if the dependency succeeded.
       - ``on_failure``: run only if the dependency failed (cleanup,
         rollback, alerting).
       - ``on_completed``: run regardless of outcome (logging,
         notification).
    6. IDs must match ``^[a-z0-9][a-z0-9._-]*$``. Use hierarchical IDs
       like ``task-1.sub-2`` so subtasks are easy to locate.
    7. The combined task + subtask graph MUST be acyclic.
    8. Every node MUST be reachable from at least one root (a node with
       no dependencies).
    9. Do NOT include secrets, credentials, or PII in any field.
    10. Output ONLY the JSON object wrapped in a single ```json fence.
        No prose before or after.

    ## User request

    {request}
    """
).strip()


def render_plan_prompt(request: str) -> str:
    """Render the plan-generation prompt for a given user request."""
    return PLAN_GENERATION_PROMPT.format(request=request.strip())


__all__ = ["PLAN_GENERATION_PROMPT", "render_plan_prompt"]
