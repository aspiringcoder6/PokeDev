"""Common standard for prompts sent to DSH agent sessions.

Every ADLC prompt generator (blueprint, task, review, ...) should build a
:class:`DshPrompt` payload that conforms to ``prompt_schema.json`` and then
call :meth:`DshPrompt.render` to produce the final user message.

The schema is the single source of truth for the prompt structure; this
module is a thin, typed wrapper that:

- validates the payload against the JSON schema before rendering,
- renders the payload into the exact text format the DSH agent expects,
- keeps the ``<adlc:file path="...">`` reply contract consistent across
  every prompt type.

Example
-------
>>> from dsh_web_sdk.prompt_builder import DshPrompt, ReplyContract, FileSpec
>>> prompt = DshPrompt(
...     role="ADLC blueprint planner",
...     objective="Build a todo app.",
...     reply_contract=ReplyContract(
...         format="adlc-file-block",
...         summary_required=True,
...         files=[FileSpec(path="blueprint.json", format="json")],
...     ),
... )
>>> prompt.render()
'You are the ADLC blueprint planner. ...'
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).with_name("prompt_schema.json")


def load_prompt_schema() -> dict[str, Any]:
    """Load the canonical prompt JSON schema from disk."""
    with _SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True, slots=True)
class FileSpec:
    """One file block the agent must include in its reply."""

    path: str
    format: str  # noqa: A003 - mirrors the JSON schema field name.
    schema_ref: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyContract:
    """The exact shape the agent's reply must take."""

    format: str  # "adlc-file-block" | "json-only" | "markdown" | "free-text"
    summary_required: bool = True
    files: list[FileSpec] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Catalogue:
    """One catalogue of items the agent may reference."""

    catalogue_id: str
    items: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PromptContext:
    """Structured context the agent needs to complete the objective."""

    current_state: dict[str, Any] | None = None
    catalogues: list[Catalogue] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DshPrompt:
    """A prompt payload that conforms to ``prompt_schema.json``.

    Use :meth:`render` to produce the final user message sent to the DSH
    agent session. Use :meth:`to_dict` to inspect the structured payload.
    """

    role: str
    objective: str
    reply_contract: ReplyContract
    instructions: str | None = None
    context: PromptContext = field(default_factory=PromptContext)

    def to_dict(self) -> dict[str, Any]:
        """Return the structured payload (matches the JSON schema)."""
        payload: dict[str, Any] = {
            "role": self.role,
            "objective": self.objective,
            "reply_contract": {
                "format": self.reply_contract.format,
                "summary_required": self.reply_contract.summary_required,
                "files": [
                    {
                        "path": spec.path,
                        "format": spec.format,
                        **({"schema_ref": spec.schema_ref} if spec.schema_ref else {}),
                        **({"description": spec.description} if spec.description else {}),
                    }
                    for spec in self.reply_contract.files
                ],
                "rules": list(self.reply_contract.rules),
            },
        }
        if self.instructions:
            payload["instructions"] = self.instructions
        context: dict[str, Any] = {}
        if self.context.current_state is not None:
            context["current_state"] = self.context.current_state
        if self.context.catalogues:
            context["catalogues"] = [
                {"catalogue_id": cat.catalogue_id, "items": list(cat.items)}
                for cat in self.context.catalogues
            ]
        if self.context.inputs:
            context["inputs"] = dict(self.context.inputs)
        if self.context.constraints:
            context["constraints"] = dict(self.context.constraints)
        if self.context.metadata:
            context["metadata"] = dict(self.context.metadata)
        if context:
            payload["context"] = context
        return payload

    def render(self) -> str:
        """Render the payload into the final user message for the DSH agent."""
        lines: list[str] = [f"You are {self.role}.", "", "# Objective", self.objective.strip()]
        if self.instructions and self.instructions.strip():
            lines.extend(["", "# Extra instructions", self.instructions.strip()])

        if self.context.current_state:
            lines.extend(
                [
                    "",
                    "# Current state",
                    json.dumps(
                        self.context.current_state,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        default=str,
                    ),
                ]
            )

        for catalogue in self.context.catalogues:
            lines.extend(
                [
                    "",
                    f"# Catalogue: {catalogue.catalogue_id}",
                    json.dumps(
                        catalogue.items,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        default=str,
                    ),
                ]
            )

        if self.context.inputs:
            lines.extend(
                [
                    "",
                    "# Inputs",
                    json.dumps(
                        self.context.inputs,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        default=str,
                    ),
                ]
            )

        if self.context.constraints:
            lines.extend(
                [
                    "",
                    "# Constraints",
                    json.dumps(
                        self.context.constraints,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        default=str,
                    ),
                ]
            )

        if self.context.metadata:
            lines.extend(
                [
                    "",
                    "# Metadata",
                    json.dumps(
                        self.context.metadata,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        default=str,
                    ),
                ]
            )

        lines.extend(["", "# Reply contract"])
        if self.reply_contract.summary_required:
            lines.append("Reply with a short summary followed by the structured payload below.")
        else:
            lines.append("Reply with only the structured payload below (no summary).")

        if self.reply_contract.format == "adlc-file-block":
            for spec in self.reply_contract.files:
                lines.append("")
                lines.append(f'<adlc:file path="{spec.path}">')
                lines.append(f"...complete {spec.format} content...")
                lines.append("</adlc:file>")
                if spec.description:
                    lines.append(f"# {spec.description}")
        elif self.reply_contract.format == "json-only":
            lines.append("Return a single JSON object as the entire reply body.")
        elif self.reply_contract.format == "markdown":
            lines.append("Return a single Markdown document as the entire reply body.")
        else:
            lines.append("Return free-form text as the entire reply body.")

        if self.reply_contract.rules:
            lines.extend(["", "Rules:"])
            lines.extend(f"- {rule}" for rule in self.reply_contract.rules)

        return "\n".join(lines)


__all__ = [
    "Catalogue",
    "DshPrompt",
    "FileSpec",
    "PromptContext",
    "ReplyContract",
    "load_prompt_schema",
]
