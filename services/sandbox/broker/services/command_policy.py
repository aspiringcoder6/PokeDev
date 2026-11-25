"""Command Policy Engine — static safety & spec-conformance gate for runShellCommand.

Single enforcement point at the Broker (every client — agents, remote.py CLI,
dashboard Action Console — reaches the shell through POST /api/v1/agent/execute).
The Go runner stays a dumb executor; policy lives here where it is auditable and
config-driven (broker/command-policy.json, override via COMMAND_POLICY_FILE).

Tiers (evaluated per shell segment split on && || ; | newline):
  1. DENY   — destructive / escape patterns (rm at /, dd of=/dev, fork bomb,
              curl|sh, sudo, mount, writes to /etc...) -> BLOCK always.
  2. FILE-MUTATION — commands that create/modify workspace files bypass the
     VFS dual-write contract:
       - blockFirstWords (touch/tee/truncate) and workspace-file redirections
         (x > file, x >> file) -> BLOCK with a runWriteFile redirect hint.
       - warnFirstWords (cp/mv/mkdir/ln/sed...) -> executed with a specWarning.
       - A segment whose first word is a toolchain (npm, pip, go, make, git...)
         skips Tier 2 entirely (build tools legitimately create many files,
         which ignore-rules already filters out of VFS concerns).
  3. ALLOW — everything else.

Policy "mode": "enforce" (default) blocks; "audit" downgrades blocks to warns.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_CONFIG_PATH = (
    os.environ.get("COMMAND_POLICY_FILE")
    or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "command-policy.json",
    )
)

_SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
_REDIRECT_RE = re.compile(r"(?<![\d&])>{1,2}\s*([^\s;&|>]+)")


class PolicyResult:
    def __init__(self, verdict: str, reason: str, matched: str = "", suggestion: Optional[str] = None):
        self.verdict = verdict          # "block" | "warn" | "allow"
        self.reason = reason
        self.matched = matched
        self.suggestion = suggestion

    def to_dict(self) -> Dict[str, Any]:
        return {"verdict": self.verdict, "reason": self.reason, "matched": self.matched, "suggestion": self.suggestion}


class CommandPolicy:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or _CONFIG_PATH
        cfg: Dict[str, Any] = {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        self.mode: str = cfg.get("mode", "enforce")
        deny_cfg = cfg.get("deny", {})
        self._deny_patterns: List[re.Pattern] = [
            re.compile(p, re.IGNORECASE) for p in deny_cfg.get("patterns", [])
        ]
        fm = cfg.get("fileMutation", {})
        self._block_first_words = set(fm.get("blockFirstWords", []))
        self._warn_first_words = set(fm.get("warnFirstWords", []))
        self._redirect_allow = tuple(fm.get("redirectTargetAllowlist", ["/dev/"]))
        self._toolchain_first_words = set(fm.get("toolchainFirstWords", []))
        self._suggestion_file_mutation = (cfg.get("suggestion", {}) or {}).get("fileMutation", "")

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _segments(command: str) -> List[str]:
        return [s.strip() for s in _SEGMENT_SPLIT.split(command or "") if s.strip()]

    @staticmethod
    def _first_word(segment: str) -> str:
        """First command word, skipping leading env assignments (FOO=bar cmd)."""
        for token in segment.split():
            if "=" in token.split("/", 1)[0]:
                continue
            return token
        return ""

    # ---------------------------------------------------------------- evaluate
    def evaluate(self, command: str) -> PolicyResult:
        # --- Tier 1: DENY — matched against the FULL command string, because
        # some patterns span segments (e.g. `curl x | sh` is split by the
        # segmenter). Whitelist never applies to this tier.
        for pat in self._deny_patterns:
            m = pat.search(command or "")
            if m:
                return PolicyResult(
                    verdict="block",
                    reason=f"Dangerous command pattern rejected by policy",
                    matched=m.group(0)[:120],
                    suggestion=None,
                )

        segments = self._segments(command)

        # --- Tier 2: FILE-MUTATION fencing (per segment, whitelist-aware) ---
        warns: List[str] = []
        for seg in segments:
            first = self._first_word(seg)
            if first in self._toolchain_first_words:
                continue

            if first in self._block_first_words:
                return PolicyResult(
                    verdict="block",
                    reason=f"File-creation command '{first}' is fenced — it bypasses the VFS dual-write contract",
                    matched=seg[:120],
                    suggestion=self._suggestion_file_mutation,
                )

            # Shell redirection that creates/modifies a file (x > file, x >> file)
            for m in _REDIRECT_RE.finditer(seg):
                target = m.group(1)
                if target.startswith("/dev/") or target == "&1" or target == "&2":
                    continue
                return PolicyResult(
                    verdict="block",
                    reason="Shell redirection writing a workspace file is fenced — it bypasses the VFS dual-write contract",
                    matched=seg[:120],
                    suggestion=self._suggestion_file_mutation,
                )

            if first in self._warn_first_words:
                warns.append(seg[:80])

        if warns:
            return PolicyResult(
                verdict="warn",
                reason="Command mutates the workspace via shell — VFS is NOT updated: "
                + "; ".join(warns[:3]),
                matched="; ".join(warns[:3]),
                suggestion=self._suggestion_file_mutation,
            )

        return PolicyResult(verdict="allow", reason="", matched="")


# Singleton
command_policy = CommandPolicy()
