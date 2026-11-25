"""API Explorer — oracle dạng API cho testcase xác thực API (nhóm 4.33+).

Contract mở rộng của testcase (5-field UI giữ nguyên, thêm tùy chọn):
    "api_request": {
        "method": "POST",
        "url": "/api/auth/token",
        "headers": {"Content-Type": "application/json"},
        "body": {"username": "u", "password": "p"},
        "expect": {"status": 401, "payload_subset": {"error": "invalid"}}
    }

Chạy HTTP request thật (urllib, không thêm dependency), đối chiếu status +
payload subset qua APIVerifier hiện có — deterministic, không LLM.
"""

import json
from typing import Any, Dict, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..executor.verifiers.api_verifier import APIVerifier


class ApiRequestError(Exception):
    """Không gửi được request hoặc testcase thiếu api_request."""


class ApiExplorer:
    """Thực thi một testcase dạng API và xác minh kết quả qua APIVerifier."""

    MAX_BODY_BYTES = 65536
    DEFAULT_TIMEOUT = 15.0

    def run(self, testcase: Dict[str, Any], base_url: str,
            extra_headers: Optional[Dict[str, str]] = None,
            timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """Chạy testcase API. Trả về {status, api_response, verification, evidence}.

        - PASS: status + payload subset khớp expect
        - FAIL: expect không khớp
        - ERROR: không gửi được request / testcase sai contract
        """
        request_spec = testcase.get("api_request")
        if not isinstance(request_spec, dict) or not request_spec.get("url"):
            raise ApiRequestError(
                "Testcase requires an 'api_request' object with at least 'url'")

        expect = request_spec.get("expect") or {}
        api_response, transport_error = self._send(
            request_spec, base_url, extra_headers or {}, timeout)

        if transport_error is not None:
            return {
                "status": "ERROR",
                "api_response": None,
                "verification": {"tier": "API", "status": "ERROR",
                                 "reason": transport_error},
                "evidence": [transport_error],
            }

        strategy = {
            "enabled": True,
            "expected_status": expect.get("status", 200),
            "expected_payload": expect.get("payload_subset") or {},
        }
        result = APIVerifier().verify(
            execution_result={"api_response": api_response},
            verification_strategy=strategy)

        return {
            "status": "PASS" if result.status == "PASS" else "FAIL",
            "api_response": api_response,
            "verification": {
                "tier": result.tier, "status": result.status,
                "reason": result.reason,
            },
            "evidence": list(result.evidence),
        }

    def _send(self, request_spec: Dict[str, Any], base_url: str,
              extra_headers: Dict[str, str], timeout: float):
        """Gửi request. Trả về (api_response, None) hoặc (None, error)."""
        method = str(request_spec.get("method", "GET")).upper()
        path = str(request_spec.get("url", "")).strip()
        url = path if path.startswith("http") else base_url.rstrip("/") + "/" + path.lstrip("/")

        headers = dict(request_spec.get("headers") or {})
        headers.update(extra_headers)
        data = None
        body = request_spec.get("body")
        if body is not None:
            if not isinstance(body, (str, bytes)):
                body = json.dumps(body, ensure_ascii=False)
                headers.setdefault("Content-Type", "application/json")
            data = body.encode("utf-8") if isinstance(body, str) else body

        req = urllib_request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(self.MAX_BODY_BYTES)
                return {"status_code": resp.status,
                        "body": self._parse_body(raw, resp.headers)}, None
        except urllib_error.HTTPError as exc:
            # 4xx/5xx là response hợp lệ của kịch bản NEGATIVE — vẫn verify
            raw = exc.read(self.MAX_BODY_BYTES)
            return {"status_code": exc.code,
                    "body": self._parse_body(raw, exc.headers)}, None
        except Exception as exc:  # noqa: BLE001 — transport error
            return None, "API request failed: {0}".format(exc)

    @staticmethod
    def _parse_body(raw: bytes, headers) -> Any:
        if not raw:
            return None
        content_type = ""
        try:
            content_type = (headers.get("Content-Type") or "").lower()
        except Exception:  # noqa: BLE001
            pass
        if "json" in content_type or b"application/json" in raw[:200]:
            try:
                return json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                pass
        return raw.decode("utf-8", errors="replace")
