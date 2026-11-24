"""dsh_web_sdk — async Python SDK for DeepSeek Harness web server."""
from __future__ import annotations

from .client import DshClient
from .config import DshConfig, RetryConfig
from .errors import (
    DshAuthError,
    DshConfigError,
    DshError,
    DshProtocolError,
    DshSessionError,
    DshTimeoutError,
    DshTransportError,
)
from .prompt_builder import (
    Catalogue,
    DshPrompt,
    FileSpec,
    PromptContext,
    ReplyContract,
    load_prompt_schema,
)
from .session import DshSession
from .taskloop import TERMINAL_STATUSES, TaskContract

__all__ = [
    "DshClient",
    "DshSession",
    "DshConfig",
    "RetryConfig",
    "TaskContract",
    "TERMINAL_STATUSES",
    "DshError",
    "DshAuthError",
    "DshConfigError",
    "DshProtocolError",
    "DshSessionError",
    "DshTimeoutError",
    "DshTransportError",
    "Catalogue",
    "DshPrompt",
    "FileSpec",
    "PromptContext",
    "ReplyContract",
    "load_prompt_schema",
]
