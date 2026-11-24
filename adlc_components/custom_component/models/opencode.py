import os
from typing import Any, AsyncIterator, Iterator
from langflow.base.models.model import LCModelComponent
from langflow.field_typing import LanguageModel
from lfx.io import MessageTextInput, SliderInput, SecretStrInput, DropdownInput, MultilineInput, Output
from lfx.schema.message import Message
from langflow.field_typing.range_spec import RangeSpec
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessageChunk


def _normalize_model_name(name: str) -> str:
    name = (name or "").strip()
    for prefix in ("opencode/", "opencode-go/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _extract_chunk_info(chunk: Any) -> tuple[str, str]:
    """Extract (reasoning, main_content) safely from any Langchain chunk object."""
    msg = getattr(chunk, "message", chunk)
    additional_kwargs = getattr(msg, "additional_kwargs", {}) or {}
    if not isinstance(additional_kwargs, dict):
        additional_kwargs = {}

    reasoning = (
        additional_kwargs.get("reasoning_content")
        or additional_kwargs.get("reasoning")
        or ""
    )

    gen_info = getattr(chunk, "generation_info", {}) or {}
    if not reasoning and isinstance(gen_info, dict):
        reasoning = (
            gen_info.get("reasoning_content")
            or gen_info.get("reasoning")
            or ""
        )

    main_content = getattr(msg, "content", "") or getattr(chunk, "text", "") or ""
    if not isinstance(main_content, str):
        main_content = str(main_content) if main_content is not None else ""

    return str(reasoning), main_content


def _build_chunk_with_text(template_chunk: Any, new_text: str) -> Any:
    """Build a chunk object preserving the original chunk structure."""
    if hasattr(template_chunk, "message"):
        try:
            from langchain_core.outputs import ChatGenerationChunk
            return ChatGenerationChunk(
                message=AIMessageChunk(content=new_text),
                text=new_text,
                generation_info=getattr(template_chunk, "generation_info", None),
            )
        except Exception:
            pass
    return AIMessageChunk(content=new_text)


class StreamingOpenCodeChatModel(ChatOpenAI):
    """
    Custom ChatOpenAI model that intercepts reasoning_content (thinking tokens)
    and wraps them in <think>...</think> tags so Langflow stream handler
    and Frontend can stream and render ThinkingRow in realtime.
    """

    def _stream(self, *args, **kwargs) -> Iterator[Any]:
        has_started_think = False
        has_ended_think = False
        last_chunk = None

        for chunk in super()._stream(*args, **kwargs):
            last_chunk = chunk
            reasoning, main_content = _extract_chunk_info(chunk)

            if reasoning:
                if not has_started_think:
                    has_started_think = True
                    yield _build_chunk_with_text(chunk, f"<think>{reasoning}")
                else:
                    yield _build_chunk_with_text(chunk, reasoning)
            elif main_content:
                if has_started_think and not has_ended_think:
                    has_ended_think = True
                    yield _build_chunk_with_text(chunk, f"</think>\n{main_content}")
                else:
                    yield chunk
            else:
                yield chunk

        if has_started_think and not has_ended_think and last_chunk:
            yield _build_chunk_with_text(last_chunk, "</think>\n")

    async def _astream(self, *args, **kwargs) -> AsyncIterator[Any]:
        has_started_think = False
        has_ended_think = False
        last_chunk = None

        async for chunk in super()._astream(*args, **kwargs):
            last_chunk = chunk
            reasoning, main_content = _extract_chunk_info(chunk)

            if reasoning:
                if not has_started_think:
                    has_started_think = True
                    yield _build_chunk_with_text(chunk, f"<think>{reasoning}")
                else:
                    yield _build_chunk_with_text(chunk, reasoning)
            elif main_content:
                if has_started_think and not has_ended_think:
                    has_ended_think = True
                    yield _build_chunk_with_text(chunk, f"</think>\n{main_content}")
                else:
                    yield chunk
            else:
                yield chunk

        if has_started_think and not has_ended_think and last_chunk:
            yield _build_chunk_with_text(last_chunk, "</think>\n")


class OpenCodeModel(LCModelComponent):
    # Định nghĩa thông tin hiển thị trên UI
    display_name = "OpenCode Model"
    description = "Kết nối với AI provider OpenCode qua endpoint Zen v1 (https://opencode.ai/zen/v1)."
    icon = "code"
    requirements = ["langchain-openai"]

    FREE_MODELS = [
        "MiniMax/MiniMax-M3",
        "deepseek-v4-flash-free",
        "nemotron-3-ultra-free",
        "laguna-s-2.1-free",
        "mimo-v2.5-free",
        "big-pickle",
        "north-mini-code-free",
        "hy3-free",
    ]

    # Định nghĩa các Input cho Node trên giao diện
    inputs = [
        MessageTextInput(
            name="base_url",
            display_name="OpenCode Base URL",
            value="https://opencode.ai/zen/v1",
        ),
        SecretStrInput(
            name="api_key",
            display_name="API Key",
            info="Nhập API Key của OpenCode Zen (https://opencode.ai/auth).",
            required=True,
        ),
        MessageTextInput(
            name="model_name",
            display_name="Model Name",
            info="Tên mô hình (ví dụ: MiniMax/MiniMax-M3, deepseek-v4-flash-free,...).",
            value="MiniMax/MiniMax-M3",
        ),
        SliderInput(
            name="temperature",
            display_name="Temperature",
            value=0.7,
            range_spec=RangeSpec(min=0.0, max=1.0, step=0.01),
        ),
        MultilineInput(
            name="input_value",
            display_name="Input Message",
            info="Tin nhắn đầu vào từ người dùng (nếu chạy trực tiếp).",
            value="",
        ),
    ]

    # Định nghĩa các cổng đầu ra trên UI
    outputs = [
        Output(name="model", display_name="Model Response", method="build_model"),
        Output(name="response", display_name="Response", method="message_response"),
    ]

    # Phương thức cốt lõi trả về đối tượng Model cho Langflow sử dụng
    def build_model(self) -> LanguageModel:
        base_url = self.base_url or "https://opencode.ai/zen/v1"
        raw_model = self.model_name or "MiniMax/MiniMax-M3"
        model_name = _normalize_model_name(raw_model) or "MiniMax/MiniMax-M3"
        temperature = self.temperature

        api_key_val = ""
        if self.api_key:
            if hasattr(self.api_key, "get_secret_value"):
                api_key_val = self.api_key.get_secret_value() or ""
            else:
                api_key_val = str(self.api_key) or ""
        if not api_key_val:
            api_key_val = os.environ.get("OPENCODE_API_KEY", "").strip()
        if not api_key_val:
            raise ValueError(
                "Chưa có API key. Hãy dán API Key OpenCode Zen vào ô 'API Key' "
                "hoặc đặt biến môi trường OPENCODE_API_KEY."
            )

        # Header giả lập opencode CLI để tránh bị rate limit pool free-tier API
        default_headers = {
            "User-Agent": "opencode/1.18.19",
            "x-opencode-client": "opencode",
            "x-opencode-request": "opencode",
            "Accept": "application/json",
        }

        return StreamingOpenCodeChatModel(
            base_url=base_url,
            api_key=api_key_val,
            model=model_name,
            temperature=temperature,
            default_headers=default_headers,
            streaming=True,
        )

    # Phương thức thực thi model trực tiếp và trả về Message
    def message_response(self) -> Message:
        model = self.build_model()

        input_text = self.input_value
        if not isinstance(input_text, str):
            if hasattr(input_text, "text") and isinstance(input_text.text, str):
                input_text = input_text.text
            elif hasattr(input_text, "content") and isinstance(input_text.content, str):
                input_text = input_text.content
            else:
                input_text = str(input_text) if input_text is not None else ""

        if not input_text:
            return Message(text="")

        full_text = ""
        try:
            for chunk in model.stream(input_text):
                full_text += chunk.content if hasattr(chunk, "content") else str(chunk)
        except Exception:
            response = model.invoke(input_text)
            full_text = response.content if hasattr(response, "content") else str(response)

        return Message(text=full_text)
