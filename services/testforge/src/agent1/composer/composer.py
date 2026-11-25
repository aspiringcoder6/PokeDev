"""Composer (Bước 2.5): chunks từ Agent Memory -> Standard Test Input 5 trường.

Vai trò trong pipeline (trước đây là khoảng trống — caller phải tự soạn 5-field):

    fetch-testcase (raw chunks cognee) -> COMPOSER (LLM + grounding + validate)
    -> 5-field hợp lệ IN001-IN005 -> broker input_inline -> Explorer -> Replay -> Gate.

Nguyên tắc (khớp triết lý Zero-Data-Fabrication của pipeline):
- LLM CHỈ được dùng thông tin trong CONTEXT (chunks recall từ cognee); prompt cấm
  chế literal value / tên màn hình không có trong tài liệu.
- Grounding (overlap từ vựng output <-> context) là CHẮN khi bật threshold: mỗi mảnh
  feature/step/expected phải che phủ >= threshold; thấp hơn -> retry kèm feedback
  các mảnh vi phạm; hết attempts -> ok=False (chặn testcase bịa từ tầng soạn).
- LLM judge (tùy chọn, enable_judge): gọi LLM lần 2 đối chiếu 5-field với đoạn gốc —
  bắt sai lệch NGỮ NGHĨA mà từ vựng đúng vẫn lọt (ghép sai bước, expected của chức
  năng khác). Mismatch -> retry với danh sách khác biệt; judge không parse được ->
  bỏ qua an toàn (ghi provenance).
- Output bắt buộc đi qua schemas/standard_test_input.schema.json (IN001-IN005);
  không hợp lệ -> retry kèm feedback lỗi (max_attempts); vẫn fail -> trả errors,
  KHÔNG bao giờ trả 5-field "gần đúng".
- Không có LLM runtime (chưa cấu hình key) -> ok=False với lỗi rõ ràng, không crash.
"""

import json
import re
from typing import Any, Dict, List, Optional

from ..explorer.standard_input import validate_standard_input
from ..healer.llm_client import OpenCodeChatClient, extract_json_object

# Stopword phổ biến VI/EN — loại khỏi grounding overlap (độ dài < 4 đã lọc phần lớn)
_STOPWORDS = {
    "with", "that", "this", "from", "into", "when", "then", "should", "will",
    "các", "và", "của", "vào", "trên", "cho", "theo", "một", "những", "được",
    "hiển", "thị", "thông", "trong", "khi", "nút", "trang", "màn", "hình",
}

_SCHEMA_HINT = """{
  "function_id": "string, mã chức năng dạng FUNC-<MODULE>-<VIỆT_TẮT>, VD FUNC-PTT-SEARCH-QUICK",
  "feature": "string, tên chức năng ngắn gọn (lấy từ cột 'Tên chức năng' trong tài liệu)",
  "precondition": ["danh sách điều kiện tiên quyết: đã đăng nhập, có quyền..."],
  "steps": ["các bước thao tác UI, mỗi bước MỘT hành động, mệnh lệnh ngắn gọn"],
  "expected_result": ["kết quả mong đợi quan sát được trên UI"]
}"""


def _norm(text: str) -> str:
    """Chuẩn hóa so khớp: lowercase + gọn whitespace."""
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _significant_words(text: str) -> List[str]:
    """Từ 'có nghĩa' (>=4 ký tự, không stopword) — dùng cho grounding overlap."""
    return [
        w for w in re.findall(r"[a-zà-ỹ0-9]{4,}", _norm(text))
        if w not in _STOPWORDS
    ]


class TestcaseComposer:
    """Soạn 5-field Standard Test Input từ raw chunks (LLM + validate + grounding)."""

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        max_attempts: int = 2,
        chunk_window: int = 6000,
        grounding_threshold: float = 0.5,
        enable_judge: bool = False,
    ):
        self.llm = llm_client if llm_client is not None else OpenCodeChatClient(timeout_seconds=120)
        self.max_attempts = max(1, int(max_attempts))
        self.chunk_window = int(chunk_window)
        # <= 0 tắt chặn grounding (chỉ còn cảnh báo provenance như bản cũ)
        self.grounding_threshold = float(grounding_threshold)
        self.enable_judge = bool(enable_judge)

    # ------------------------------------------------------------------
    # API chính
    # ------------------------------------------------------------------
    def compose(
        self,
        chunks: List[Dict[str, Any]],
        query: str = "",
        function_id: str = "",
        dataset: str = "",
    ) -> Dict[str, Any]:
        """Chunks -> 5-field hợp lệ (hoặc errors). Không raise.

        Returns:
            {"ok", "standard_input", "errors", "grounded", "grounded_ratio",
             "attempts", "provenance"}
        """
        provenance = {
            "stage": "composer",
            "dataset": dataset,
            "query": query,
            "function_id_hint": function_id,
            "llm_model": getattr(self.llm, "model", None),
            "chunks": [],
        }
        if not chunks:
            return self._fail(provenance, ["NO_CONTEXT: không có chunk nào từ Agent Memory"])

        context, used = self._build_context(chunks, query)
        provenance["chunks"] = used
        source_text = _norm(context)

        if not getattr(self.llm, "available", lambda: bool(self.llm))():
            return self._fail(provenance, [
                "LLM_UNAVAILABLE: chưa cấu hình LLM (OPENCODE_API_KEY / opencode.json)"
            ])

        errors: List[str] = []
        std: Optional[Dict[str, Any]] = None
        attempts = 0
        feedback = ""
        g_ratio, g_detail = 0.0, []
        for attempts in range(1, self.max_attempts + 1):
            content = self._call_llm(context, query, function_id, feedback)
            if not content:
                errors = ["LLM_NO_OUTPUT: LLM không trả nội dung (lần {0})".format(attempts)]
                feedback = "Lần trước bạn không trả về gì. Hãy trả về DUY NHẤT một JSON object."
                continue
            std = extract_json_object(content)
            if std is None:
                errors = ["LLM_NO_JSON: response không chứa JSON object (lần {0})".format(attempts)]
                feedback = ("Response trước không parse được JSON. Trả về DUY NHẤT một "
                            "JSON object đúng schema, không kèm chữ ngoài JSON.")
                std = None
                continue
            errors = [str(e) for e in validate_standard_input(std)]
            if errors:
                feedback = ("JSON trước vi phạm schema Standard Test Input:\n- "
                            + "\n- ".join(errors[:6])
                            + "\nSửa lại, trả về DUY NHẤT một JSON object hợp lệ.")
                std = None
                continue

            g_ratio, g_detail = self._grounding(std, source_text)
            if self.grounding_threshold > 0 and g_ratio < self.grounding_threshold:
                offending = [d for d in g_detail if d["ratio"] < self.grounding_threshold]
                errors = [
                    "GROUNDING_LOW: độ che phủ {0:.2f} < threshold {1:.2f}".format(
                        g_ratio, self.grounding_threshold)
                ] + ["mảnh thấp: '{0}' ({1:.2f})".format(d["text"], d["ratio"]) for d in offending[:4]]
                feedback = (
                    "Các mảnh sau KHÔNG có (hoặc rất ít) trong CONTEXT — bạn đã bịa hoặc "
                    "đổi từ ngữ so với tài liệu. Phải dùng ĐÚNG từ ngữ/tên như CONTEXT:\n- "
                    + "\n- ".join("{0} (che phủ {1:.0%})".format(d["text"], d["ratio"]) for d in offending[:6])
                    + "\nSoạn lại DUY NHẤT một JSON object."
                )
                std = None
                continue

            if self.enable_judge:
                verdict = self._judge(std, context)
                if verdict is None:
                    provenance["judge"] = {"skipped": "judge không trả JSON hợp lệ — bỏ qua"}
                else:
                    provenance["judge"] = verdict
                    if not verdict.get("match", False):
                        diffs = [str(d) for d in (verdict.get("differences") or [])]
                        errors = (["JUDGE_MISMATCH: thẩm định đối chiếu tài liệu phát hiện khác biệt"]
                                  + diffs[:5])
                        feedback = (
                            "Thẩm định viên đối chiếu với CONTEXT phát hiện các khác biệt — sửa "
                            "cho trung thực với tài liệu:\n- " + "\n- ".join(diffs[:6] or ["(không rõ)"])
                            + "\nSoạn lại DUY NHẤT một JSON object."
                        )
                        std = None
                        continue
            break

        provenance["grounding"] = g_detail
        if std is None:
            return self._fail(provenance, errors, attempts=attempts)

        provenance["attempts"] = attempts
        provenance["llm_usage"] = getattr(self.llm, "last_usage", None)
        return {
            "ok": True,
            "standard_input": std,
            "errors": [],
            "grounded": g_ratio >= 0.5,
            "grounded_ratio": round(g_ratio, 3),
            "grounding_threshold": self.grounding_threshold,
            "attempts": attempts,
            "provenance": provenance,
        }

    # ------------------------------------------------------------------
    # Context: window quanh vị trí khớp query trong mỗi chunk
    # ------------------------------------------------------------------
    def _build_context(
        self, chunks: List[Dict[str, Any]], query: str
    ) -> tuple:
        """Mỗi chunk (40-55k chars) chỉ lấy window quanh vùng khớp query nhất
        để context vừa token limit — position chọn bằng đếm token truy vấn."""
        q_tokens = [w for w in _significant_words(query)]
        # Số mục (VD "4.6.2.6") là định danh tuyệt đối trong tài liệu — khớp chính xác
        # ưu tiên hơn token (từ chức năng chung như "phong trào" xuất hiện khắp PTYC).
        section_num = None
        m = re.search(r"\d+(?:\.\d+){1,3}", query or "")
        if m:
            section_num = m.group(0)
        used: List[Dict[str, Any]] = []
        parts: List[str] = []
        scan_window = min(2000, self.chunk_window)
        for idx, chunk in enumerate(chunks):
            text = str(chunk.get("text") or "")
            if not text:
                continue
            low = text.lower()
            best_pos, best_score = 0, -1
            if section_num and section_num in low:
                best_pos, best_score = low.find(section_num), 10**6
            elif q_tokens:
                step = max(1, len(low) // 400)
                for pos in range(0, max(1, len(low) - scan_window), step):
                    window = low[pos:pos + scan_window]
                    score = sum(window.count(t) for t in q_tokens)
                    if score > best_score:
                        best_pos, best_score = pos, score
            # Thiên về phía trước: token khớp thường là TIÊU ĐỀ mục (4.6.x.y),
            # nội dung bảng/bước nằm ngay sau — lấy window từ vị trí khớp trở đi.
            start = best_pos
            end = min(len(text), start + self.chunk_window)
            excerpt = text[start:end]
            used.append({
                "index": idx,
                "document_id": chunk.get("document_id"),
                "chunk_chars": len(text),
                "excerpt_chars": len(excerpt),
                "excerpt_offset": start,
                "match_score": best_score,
            })
            parts.append(
                "[CHUNK {0} | doc={1} | offset={2}]\n{3}".format(
                    idx + 1, chunk.get("document_id") or "?", start, excerpt)
            )
        return "\n\n".join(parts), used

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def _call_llm(
        self, context: str, query: str, function_id: str, feedback: str
    ) -> Optional[str]:
        system = (
            "Bạn là chuyên viên phân tích kiểm thử. Nhiệm vụ: từ ngữ cảnh tài liệu "
            "phân tích yêu cầu (PTYC) được cung cấp, soạn MỘT Standard Test Input "
            "dạng JSON 5 trường.\n"
            "Quy tắc bắt buộc:\n"
            "1. CHỈ dùng thông tin có trong CONTEXT. Cấm bịa tên màn hình, tên nút, "
            "giá trị literal không có trong tài liệu.\n"
            "2. Mỗi step là MỘT hành động UI rõ ràng (mở menu, bấm nút, nhập ô...), "
            "viết mệnh lệnh ngắn, giữ nguyên tên chức năng/nút như tài liệu.\n"
            "3. precondition chỉ ghi điều kiện phiên/quyền (đã đăng nhập, có quyền...).\n"
            "4. expected_result là kết quả quan sát được trên UI, suy từ tài liệu.\n"
            "5. Trả về DUY NHẤT một JSON object, không giải thích, không markdown fence."
        )
        user = (
            "QUERY: {0}\n".format(query)
            + ("FUNCTION_ID bắt buộc dùng: {0}\n".format(function_id) if function_id
               else "function_id: tự đặt theo quy ước FUNC-<MODULE>-<VIỆT_TẮT> từ tên chức năng.\n")
            + (("\nFEEDBACK lần trước (phải sửa):\n" + feedback + "\n") if feedback else "")
            + "\nCONTEXT tài liệu:\n" + context
            + "\n\nSchema JSON cần trả:\n" + _SCHEMA_HINT
        )
        return self.llm.chat(system, user)

    # ------------------------------------------------------------------
    # LLM judge: thẩm định ngữ nghĩa 5-field <-> đoạn gốc (tùy chọn)
    # ------------------------------------------------------------------
    def _judge(self, std: Dict[str, Any], context: str) -> Optional[Dict[str, Any]]:
        """Gọi LLM lần 2 đối chiếu 5-field với CONTEXT.

        Returns:
            {"match": bool, "differences": [str]} hoặc None khi không parse được
            (None = bỏ qua an toàn, không chặn pipeline).
        """
        system = (
            "Bạn là thẩm định viên kiểm thử. Nhiệm vụ: đối chiếu Standard Test Input "
            "(5 trường) với CONTEXT tài liệu phân tích yêu cầu.\n"
            "Chỉ báo khác biệt NGHIỆP VỤ:\n"
            "- sai tên chức năng / sai màn hình\n"
            "- bước thừa, bước thiếu, hoặc thứ tự bước khác tài liệu\n"
            "- expected_result không phải kết quả tài liệu mô tả\n"
            "- giá trị literal / tên nút không có trong tài liệu\n"
            "KHÔNG báo khác biệt văn phong hay từ đồng nghĩa.\n"
            "Trả về DUY NHẤT JSON: "
            '{"match": true hoặc false, "differences": ["mỗi khác biệt một chuỗi ngắn"]}'
        )
        user = (
            "STANDARD TEST INPUT cần thẩm định:\n"
            + json.dumps(std, ensure_ascii=False, indent=2)
            + "\n\nCONTEXT tài liệu gốc:\n" + context
        )
        content = self.llm.chat(system, user)
        if not content:
            return None
        verdict = extract_json_object(content)
        if verdict is None or not isinstance(verdict.get("match"), bool):
            return None
        if not isinstance(verdict.get("differences"), list):
            verdict["differences"] = []
        return verdict

    # ------------------------------------------------------------------
    # Grounding: overlap từ vựng output <-> context
    # ------------------------------------------------------------------
    def _grounding(self, std: Dict[str, Any], source_text: str) -> tuple:
        """Độ che phủ từ vựng output <-> context theo TỪNG mảnh (feature/steps/expected).

        Dùng MIN (không trung bình): một mảnh bịa giữa các mảnh đúng vẫn phải bị
        phát hiện. Không chặn — chỉ làm bằng chứng provenance (Gate/HITL quyết định).
        """
        pieces: List[str] = [str(std.get("feature") or "")]
        pieces += [str(s) for s in (std.get("steps") or [])]
        pieces += [str(e) for e in (std.get("expected_result") or [])]

        ratios: List[float] = []
        detail: List[Dict[str, Any]] = []
        for piece in pieces:
            words = _significant_words(piece)
            if not words:
                continue
            hits = sum(1 for w in words if w in source_text)
            ratio = hits / len(words)
            ratios.append(ratio)
            detail.append({
                "text": piece[:80],
                "hits": hits,
                "words": len(words),
                "ratio": round(ratio, 2),
            })
        overall = min(ratios) if ratios else 0.0
        return overall, detail

    # ------------------------------------------------------------------
    @staticmethod
    def _fail(provenance: Dict[str, Any], errors: List[str], attempts: int = 0) -> Dict[str, Any]:
        provenance["attempts"] = attempts
        return {
            "ok": False,
            "standard_input": None,
            "errors": errors,
            "grounded": False,
            "grounded_ratio": 0.0,
            "attempts": attempts,
            "provenance": provenance,
        }
