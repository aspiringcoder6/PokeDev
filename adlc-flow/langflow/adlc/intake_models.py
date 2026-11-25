"""LI-01 commands. Source, ownership and authority are assigned by the server."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class IntakeContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    description: Description
    scope_in: list[Line] = Field(default_factory=list, max_length=50)
    scope_out: list[Line] = Field(default_factory=list, max_length=50)
    constraints: list[Line] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[Line] = Field(default_factory=list, max_length=50)
    assumptions: list[Line] = Field(default_factory=list, max_length=50)


class CreateIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    project_id: UUID | None = None
    content: IntakeContent


class UpdateIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_revision: int = Field(strict=True, ge=1)
    content: IntakeContent


class CancelIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_revision: int = Field(strict=True, ge=1)
