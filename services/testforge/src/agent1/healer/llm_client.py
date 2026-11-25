"""LLM Client cho Tier 2 (Bước 16.2) — chuẩn OpenAI-compatible.

Theo pattern `adlc_components/custom_component/models/opencode.py` của nhóm ADLC:
- POST {base_url}/chat/completions (OpenAI-compatible)
- Header giả lập opencode CLI để tránh rate-limit pool free-tier
- KHÔNG BAO GIỜ hardcode API key: đọc từ env OPENCODE_API_KEY; nếu không có,
  fallback đọc cấu hình local `opencode.json` (file đã gitignore).

Provider-agnostic: hoạt động với OpenCode Zen, netmind gateway, OpenAI...

Graceful degradation: nếu chưa cấu hình key -> available() == False -> Tier 2
dùng heuristic fallback (không fail pipeline).
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


class OpenCodeChatClient:
    """Client chat completion tối giản, chuẩn OpenAI-compatible."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        timeout_seconds: int = 45,
    ):
        cfg = self._load_opencode_json_config()
        self.base_url = (base_url or os.environ.get("OPENCODE_BASE_URL") or cfg.get("base_url") or "").rstrip("/")
        self.api_key = (api_key or os.environ.get("OPENCODE_API_KEY") or cfg.get("api_key") or "").strip()
        self.model = model or os.environ.get("TESTFORGE_LLM_MODEL") or cfg.get("model") or "MiniMax/MiniMax-M3"
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.last_usage: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    @staticmethod
    def _load_opencode_json_config() -> Dict[str, Any]:
        """Đọc provider đầu tiên từ opencode.json (repo) hoặc ~/.config/opencode (JSONC).

        Returns: {"base_url", "api_key", "model"} hoặc rỗng nếu không có file hợp lệ.
        """
        candidates = [
            Path(__file__).resolve().parents[4] / "opencode.json",
            Path.home() / ".config" / "opencode" / "opencode.jsonc",
            Path.home() / ".config" / "opencode" / "opencode.json",
        ]
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8")
                if path.suffix == ".jsonc":
                    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
                    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
                    text = re.sub(r",(\s*[}\]])", r"\1", text)
                data = json.loads(text)
                provider = next(iter((data.get("provider") or {}).values()), {})
                options = provider.get("options") or {}
                models = list((provider.get("models") or {}).keys())
                config = {
                    "base_url": options.get("baseURL", ""),
                    "api_key": options.get("apiKey", ""),
                    "model": models[0] if models else "",
                }
                if config["api_key"] and config["base_url"]:
                    return config
            except (OSError, ValueError, KeyError, StopIteration):
                continue
        return {}

    def available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    # ------------------------------------------------------------------
    def chat(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Gọi chat completion, trả về content text (hoặc None khi lỗi).

        Không raise — Tier 2 chỉ cần fallback heuristic khi LLM hỏng.
        """
        if not self.available():
            return None
        try:
            import httpx
            payload = {
                "model": self.model,
                "temperature": self.temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # Giả lập opencode CLI — tránh rate-limit pool free-tier (kinh nghiệm nhóm ADLC)
                "User-Agent": "opencode/1.18.19",
                "x-opencode-client": "opencode",
                "x-opencode-request": "opencode",
                "Accept": "application/json",
            }
            t0 = time.time()
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            duration_ms = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                return None
            data = resp.json()
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            usage = data.get("usage") or {}
            self.last_usage = {
                "model": self.model,
                "duration_ms": duration_ms,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            }
            return content if isinstance(content, str) and content.strip() else None
        except Exception:
            return None


def extract_json_object(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Trích JSON object đầu tiên từ response LLM (chịu được ```json fence + text thừa)."""
    if not text:
        return None
    cleaned = text.strip()
    # bỏ code fence nếu có
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                cleaned = part
                break
    start = cleaned.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None
