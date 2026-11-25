# Source Access for Requirement Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supply project-scoped GitHub/Lark evidence using application identity to both seed retrieval and agent-directed reads.

**Architecture:** Add a small source_access library behind one SourceGateway. The backend executes typed reads chosen by the collector, retains credentials, and returns immutable evidence. This plan is independently testable without DSH and is consumed by the readiness pipeline plan.

**Tech Stack:** Existing Python >=3.10,<3.15, Pydantic, httpx, PyJWT/cryptography, pytest; GitHub REST API and Lark OpenAPI. No new package is required.

**Spec:** This document, section “Tool contract”; it is the normative source-access contract for the three-stage workflow.

## Global Constraints

- Collection uses GitHub and Lark APIs; no local source checkout is required.
- Application identity owns credentials: GitHub App installation and Lark tenant app/bot; personal PAT/OAuth sessions are not the production identity.
- Every source read is authorized against the server-owned project binding.
- max_context_rounds defaults to 3 and counts collection-verification rounds including the initial round.
- Each runtime role uses its own new prompt; existing blueprint/coding prompts are not reused.
- Review A and Review B use different sessions and the same frozen snapshot; neither consumes the other's output.
- The supplied specification-router remains unchanged and is the routing authority.
- grill-me is invoked explicitly and its grilling dependency is preserved.
- Missing native skills/CLI or unresolved authorization returns blocked; no substitute checklist is silently used.
- Human clarification waits for real answers and final shared-understanding confirmation.
- Ready for specification and an existing verified specification are distinct results.
- Stage 3 uses two new independent impact sessions, then a separate ACE assess session consuming both full reports.
- The backend-owned Human Gates policy determines auto or required; model output cannot weaken it.
- Only a completed Stage 3 option selection produces the final handoff; selection does not authorize implementation, merge or deployment.

---


## Tool contract

Doc này lên kế hoạch làm tool đọc dữ liệu cho hệ thống tự chạy. SDK DSH hiện tại chỉ chuyển prompt/kết quả tới agent; chưa có sẵn connector GitHub/Lark hoặc callback thực thi các tool bên dưới. Backend sẽ thực thi các lệnh đọc có cấu trúc do agent đề xuất rồi gửi evidence lại qua SDK. Không cần clone source về local.

Mỗi lệnh dùng chung `SourceRef(kind, connection_id, resource_id, locator, revision)`; kết quả là `Evidence` có nội dung, nguồn, phiên bản, hash và cờ đầy đủ. Agent không nhận token và không tự đặt quyền. Đây là API nội bộ của backend, chưa phải MCP server hoặc tool native đã cài trong DSH.

| Tool / kind | Input cụ thể | Output | Phạm vi |
| --- | --- | --- | --- |
| GitHub tree / github_file | repo; locator tree=1; revision SHA đã resolve | Danh sách đường dẫn/blob; báo incomplete nếu truncated | Repo được GitHub App và project cùng cho phép |
| GitHub file / github_file | repo; path; cùng SHA | Text file và blob SHA | Như trên |
| GitHub Issue hoặc PR / github_issue | repo; number | Issue + toàn bộ comments; với PR thêm metadata/files/review comments cần thiết | Issues read; PR cần Pull requests read |
| GitHub related work / github_related_work | repo; keywords; state=all/open/closed; type=all/issue/pr | Danh sách Issue/PR liên quan, ID và liên kết để đọc chi tiết | Chỉ tìm trong repo được cấp; không search xuyên org |
| Lark Messenger / lark_thread | chat_id; thread_id hoặc start_time/end_time | Cụm hội thoại có root/replies, tác giả, thời điểm và pagination | App/bot có quyền đọc và nằm trong chat phù hợp |
| Lark Base / lark_base_record | app_token; table_id; record_id hoặc filter | Schema field + record/cell; các ref tài liệu/attachment | App có quyền Base và là collaborator được cấp |
| Lark document / lark_document | document_id; Wiki node nếu cần resolve | Text/blocks hoặc finding chưa trích xuất được | Phải cấp riêng cho object tài liệu thực tế |

Lark Base là bảng dữ liệu, không đồng nghĩa đã đọc được nội dung mọi file đính kèm. Liên kết tài liệu phải qua một lượt kiểm tra quyền và đọc riêng. File binary không có parser thì trả metadata + incomplete, không giả vờ đã có text. Các link ngoài GitHub/Lark và URL tùy ý không nằm trong phạm vi tool này.

### Quyền bền vững và vận hành

- GitHub: tổ chức cài GitHub App vào các repo được chọn. Backend dùng private key để xin installation token ngắn hạn, tự refresh. Quyền đọc gồm Contents, Issues và Pull requests; không cấp quyền ghi. Gỡ App/repo hoặc thu hồi quyền phải có hiệu lực ở lượt đọc tiếp theo.
- Lark: dùng ứng dụng nội bộ của tenant, app_id/app_secret do tổ chức quản lý; backend dùng tenant_access_token. Admin duyệt quyền đọc theo các endpoint sử dụng, bot được thêm vào chat, Base và tài liệu được chia sẻ cho app theo khả năng của tenant. Không tự chuyển sang user_access_token khi app bị từ chối.
- Token ngắn hạn được tự gia hạn; secret gốc vẫn phải có người vận hành luân chuyển hoặc thu hồi. “Bền vững” là không phụ thuộc phiên đăng nhập cá nhân, không có nghĩa quyền không bao giờ hết hạn.
- Project binding do backend giữ: principal nào được dùng connection nào, repo/chat/Base/document nào; với Base có table/field allowlist nếu cần hạn chế sâu hơn. Quyền app tại provider và allowlist của project phải cùng cho phép.
- Kiểm tra lại binding hiện hành trước mỗi lượt đọc; run chỉ giữ budget/checkpoint, không đóng băng quyền cũ sau khi bị thu hồi. Evidence đã lưu cần phân quyền đọc/retention tương ứng, không đưa toàn bộ evidence vào log.
- Không gửi secret, HTTP headers hay nguyên lỗi provider cho agent. Secret reference trỏ tới secret store hoặc biến môi trường backend; không commit secret vào repo.
- Tool timeout, số trang, số byte và số logical read đều có giới hạn; cùng budget xuyên cả ba bước. Search có thể incomplete; kết quả rỗng từ một tìm kiếm giới hạn không chứng minh không có dependency.
- Không có tool ghi Issue, gửi tin nhắn, sửa Base hoặc deploy trong plan này. Human interaction dùng boundary của phần người khác làm.

### Nghiệm thu

Có thể chạy mock suite mà không có DSH hoặc credential thật. Nghiệm thu live cần GitHub App installation, Lark tenant app được duyệt và fixture được chia sẻ đúng quyền. Kết quả phải chứng minh được đọc đủ trang, cố định commit code, báo rõ nguồn bị từ chối và chặn cross-project trước network I/O.

## File structure and execution environment

Create under adlc-flow/langflow/adlc/source_access/: __init__.py (exports), models.py (closed wire contracts), policy.py (grant checks/budgets), credentials.py (app tokens), github.py (remote tree/files/Issues), lark_messages.py (chat/thread), lark_base.py (schema/records/linked documents), gateway.py (dispatch/evidence merge), settings.py (connection config from secret references). Tests go under adlc-flow/tests/unit/adlc/source_access/.

Plan B owns service authentication, orchestration, SDK prompts, API routes and human continuation. Do not put an agent loop or personal login in this library.

From adlc-flow, create the independent .venv if absent and install requirements.txt. Do not clear an existing environment. Install ../sdk only for Plan B. All unit tests in this plan use MockTransport and fake token providers, never provider secrets.

Run commands from adlc-flow:
```powershell
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access -q
```
--confcutdir avoids the unrelated full-app tests/conftest.py startup fixtures. Each test imports only the new package. Keep __init__.py free of app/service construction.

### Task A1: Evidence contracts and project scope enforcement

**Files:** Create source_access/__init__.py, source_access/models.py, source_access/policy.py, source_access/gateway.py and tests/unit/adlc/source_access/test_policy.py. All source paths are relative to adlc-flow/langflow/adlc/ unless explicitly marked tests.

**Interfaces:**
- Produces SourceRef, Evidence, SourceGrant, SourceError and Reader.
- Produces SourceGateway(readers).read(grant, refs) -> list[Evidence].
- Consumes only server-created SourceGrant; no method accepts an agent-supplied grant.

- [ ] **Step 1: Write the failing test**
```python
import asyncio
import pytest
from langflow.adlc.source_access.models import SourceGrant, SourceRef, SourceError
from langflow.adlc.source_access.gateway import SourceGateway

def test_cross_project_resource_is_denied_before_reader():
    ref = SourceRef(kind="github_file", connection_id="gh", resource_id="org/private",
                    locator={"path": "README.md"}, revision="a" * 40)
    grant = SourceGrant(project_id="p1", run_id="r1", principal_id="normalizer",
                        resources={"gh": frozenset({"org/allowed"})})
    gateway = SourceGateway({})
    with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
        asyncio.run(gateway.read(grant, [ref]))
```

- [ ] **Step 2: Run red**
Run: .venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_policy.py -q
Expected: import failure for the new package.

- [ ] **Step 3: Implement the contracts and policy**
```python
# models.py
from datetime import datetime
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["github_file", "github_issue", "github_related_work", "lark_thread",
               "lark_base_record", "lark_document"]

class SourceError(ValueError):
    def __init__(self, code: str, *, retry_after: float | None = None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after

class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class SourceRef(Closed):
    kind: Kind
    connection_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    locator: dict[str, str] = Field(default_factory=dict)
    revision: str | None = None

class Evidence(Closed):
    id: str
    source: SourceRef
    version: str
    fetched_at: datetime
    body: str
    sha256: str
    complete: bool = True

class SourceGrant(Closed):
    project_id: str
    run_id: str
    principal_id: str
    resources: dict[str, frozenset[str]]
    locator_allowlists: dict[str, dict[str, tuple[str, ...]]] = Field(default_factory=dict)
    max_reads: int = Field(default=24, ge=1, le=200)
    max_bytes: int = Field(default=500_000, ge=1, le=2_000_000)

class Reader(Protocol):
    async def read(self, ref: SourceRef) -> Evidence: ...
```
```python
# policy.py
from .models import SourceError

def authorize(grant, ref):
    if ref.resource_id not in grant.resources.get(ref.connection_id, frozenset()):
        raise SourceError("SOURCE_SCOPE_DENIED")
    if any(key in ref.locator for key in ("token", "base_url", "authorization")):
        raise SourceError("SOURCE_ARGUMENTS_INVALID")
    key = ref.connection_id + ":" + ref.resource_id
    for locator_key, allowed in grant.locator_allowlists.get(key, {}).items():
        if ref.locator.get(locator_key) not in allowed:
            raise SourceError("SOURCE_SCOPE_DENIED")

# gateway.py
from .models import SourceError
from .policy import authorize

class SourceGateway:
    def __init__(self, readers):
        self.readers = readers

    async def read(self, grant, refs):
        for ref in refs:
            authorize(grant, ref)
        if len(refs) > grant.max_reads:
            raise SourceError("SOURCE_READ_LIMIT")
        result, size = [], 0
        for ref in refs:
            reader = self.readers.get((ref.connection_id, ref.kind))
            if reader is None:
                raise SourceError("SOURCE_CONNECTION_UNAVAILABLE")
            evidence = await reader.read(ref)
            size += len(evidence.body.encode("utf-8"))
            if size > grant.max_bytes:
                raise SourceError("SOURCE_CONTEXT_LIMIT")
            result.append(evidence)
        return result
```
Expose these symbols in __init__.py. Reader validation must also reject unexpected locator keys per kind in Tasks A3/A4. Deep-copy/freeze grant maps at the service boundary; do not let a shared mutable dict widen a grant. The worker tracks cumulative reads/bytes across rounds; max_reads here bounds one call, not permission to reset the run budget.

- [ ] **Step 4: Run green and add meaningful boundary coverage**
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_policy.py -q`
Expected: PASS after implementation.
Add a table-restricted project test and a second project sharing the same connection but different table grant; assert restrictions cannot bleed across runs. Add parameterized tests for absent connection, unexpected credential argument, read limit, bytes exceeding limit and known authorized result. Use a fake Reader whose call count proves denial occurs before I/O.
Expected: all new tests pass.
- [ ] **Step 5: Commit**
```powershell
git add langflow/adlc/source_access tests/unit/adlc/source_access
git commit -m "feat: define scoped source evidence access"
```

### Task A2: Application credentials with bounded refresh

**Files:** Create langflow/adlc/source_access/credentials.py and langflow/adlc/source_access/settings.py; tests/unit/adlc/source_access/test_source_credentials.py (relative to adlc-flow).

**Interfaces:**
- GitHubAppTokens(client, app_id, private_key, installation_id, clock).get(force=False) -> str.
- LarkTenantTokens(client, app_id, app_secret, clock).get(force=False) -> str.
- Both cache in memory per connection and serialize refresh using asyncio.Lock.
- ConnectionSettings identifies provider, credential secret references and installation/tenant identity. Settings resolves secret references server-side; agent payload contains connection_id only.

- [ ] **Step 1: Write red**
```python
import asyncio
import httpx
from langflow.adlc.source_access.credentials import LarkTenantTokens

def test_lark_uses_app_secret_and_caches_token():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "tenant_access_token": "fake-app-token", "expire": 7200})
    async def scenario():
        async with httpx.AsyncClient(base_url="https://open.larksuite.com",
                                     transport=httpx.MockTransport(respond)) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: 1000)
            assert await tokens.get() == await tokens.get() == "fake-app-token"
    asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0].url.path == "/open-apis/auth/v3/tenant_access_token/internal"
```
- [ ] **Step 2: Run red**
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_source_credentials.py -q`
Expected: FAIL before implementation; missing the new component or its contract.
Run the focused test with the same --confcutdir. Expected missing credentials module/class.
- [ ] **Step 3: Implement token acquisition**
Use this cache core; subclasses implement the exact app-only exchange.
```python
import asyncio
import time
from datetime import datetime
import jwt
from .models import SourceError

class CachedAppTokens:
    def __init__(self, clock=time.time):
        self.clock, self.lock = clock, asyncio.Lock()
        self.value, self.expires_at = "", 0.0

    async def get(self, force=False):
        async with self.lock:
            if not force and self.value and self.expires_at - self.clock() > 60:
                return self.value
            self.value, self.expires_at = await self.fetch()
            if not self.value or self.expires_at <= self.clock():
                raise SourceError("SOURCE_APP_AUTH_FAILED")
            return self.value

class LarkTenantTokens(CachedAppTokens):
    def __init__(self, client, app_id, app_secret, clock=time.time):
        super().__init__(clock)
        self.client, self.app_id, self.app_secret = client, app_id, app_secret

    async def fetch(self):
        response = await self.client.post("/open-apis/auth/v3/tenant_access_token/internal",
                                         json={"app_id": self.app_id, "app_secret": self.app_secret})
        data = response.json()
        if response.status_code != 200 or data.get("code") != 0:
            raise SourceError("SOURCE_APP_AUTH_FAILED")
        return data["tenant_access_token"], self.clock() + int(data["expire"])

class GitHubAppTokens(CachedAppTokens):
    def __init__(self, client, app_id, private_key, installation_id, clock=time.time):
        super().__init__(clock)
        self.client, self.app_id = client, app_id
        self.private_key, self.installation_id = private_key, installation_id

    async def fetch(self):
        now = int(self.clock())
        signed = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id},
                            self.private_key, algorithm="RS256")
        response = await self.client.post(
            f"/app/installations/{self.installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {signed}"},
            json={"permissions": {"contents": "read", "issues": "read", "pull_requests": "read"}})
        if response.status_code != 201:
            raise SourceError("SOURCE_APP_AUTH_FAILED")
        data = response.json()
        return data["token"], datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
```
Connection constructors require fixed GitHub/Lark origins, trust_env=False and follow_redirects=False. GitHub Enterprise custom host is an operator configuration extension, not an agent URL parameter. Catch JSON/key/TTL errors and convert to SOURCE_APP_AUTH_FAILED without raw response/secret text.

- [ ] **Step 4: Test**
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_source_credentials.py -q`
Expected: PASS after implementation.
Add fake-clock expiry, force refresh, malformed response and concurrent calls sharing one refresh. GitHub test uses a temporary generated RSA key and decodes the outgoing JWT with its public key; verify installation path, exp-iat <=600, and absence of personal bearer credentials. No production key is used.
- [ ] **Step 5: Commit**
```powershell
git add langflow/adlc/source_access/credentials.py langflow/adlc/source_access/settings.py tests/unit/adlc/source_access/test_source_credentials.py
git commit -m "feat: authenticate source reads as applications"
```

### Task A3: GitHub remote code, Issues/PRs and related work

**Files:** Create langflow/adlc/source_access/github.py; tests/unit/adlc/source_access/test_github_reader.py (relative to adlc-flow).
**Interfaces:** GitHubReader(client, tokens).resolve_revision(repository, ref) -> str; .read(SourceRef) -> Evidence. Task B persists the resolved commit in its SourceRef before further file reads.

- [ ] **Step 1: Write red**
```python
import asyncio
import base64
import httpx
from langflow.adlc.source_access.github import GitHubReader
from langflow.adlc.source_access.models import SourceRef

def test_file_read_uses_pinned_commit_without_checkout():
    seen = []
    class Tokens:
        async def get(self, force=False):
            return "test-installation-token"
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"sha": "blob1", "encoding": "base64",
                                       "content": base64.b64encode(b"hello").decode()})
    async def scenario():
        async with httpx.AsyncClient(base_url="https://api.github.com",
                                     transport=httpx.MockTransport(respond)) as client:
            reader = GitHubReader(client, Tokens())
            result = await reader.read(SourceRef(kind="github_file", connection_id="gh",
                resource_id="org/repo", locator={"path": "README.md"}, revision="a" * 40))
            assert result.body == "hello"
            assert result.source.revision == "a" * 40
    asyncio.run(scenario())
    assert seen[0].url.params["ref"] == "a" * 40
    assert seen[0].headers["Authorization"] == "Bearer test-installation-token"
```
- [ ] **Step 2: Run red** Focused test; expected missing GitHubReader.
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_github_reader.py -q`
Expected: FAIL before implementation; missing the new component or its contract.
- [ ] **Step 3: Implement the reader**
```python
import hashlib
from datetime import datetime, timezone
from .models import Evidence

def make_evidence(ref, body, version, *, complete=True):
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    identity = hashlib.sha256(
        (ref.model_dump_json() + "\n" + version + "\n" + content_hash).encode("utf-8")
    ).hexdigest()
    return Evidence(id=identity, source=ref, version=version,
                    fetched_at=datetime.now(timezone.utc), body=body,
                    sha256=content_hash, complete=complete)
```
Place make_evidence in models.py and export it; no duplicate implementation in Lark readers.
Implement exact dispatch rules:
- resolve_revision: GET /repos/{owner}/{repo}/commits/{ref}; return validated 40-character SHA.
- github_file requires a pinned 40-character SHA. Allowed locator keys: path or tree. For a file GET /repos/{owner}/{repo}/contents/{quoted-path}?ref={sha}; validate base64/UTF-8 and byte limit. A directory/tree request uses Git Trees with recursive=1; truncated=true is incomplete evidence.
- github_issue allowed locator key number, a positive integer. GET the Issue, then GET /issues/{number}/comments?per_page=100&page=N until no next page. If pull_request metadata is present, also GET /pulls/{number}, /pulls/{number}/files and /pulls/{number}/comments, with independent pagination. Include head/base SHA, changed paths and review comments; if the provider caps the files list, mark incomplete. Validate every pagination link stays on api.github.com and the same repo. Body is canonical JSON containing title/body/state/labels/comments/updated_at and any PR details.
- github_related_work accepts only keywords (bounded to 200 characters), state (all/open/closed), type (all/issue/pr). Use GET /repos/{owner}/{repo}/issues?state={state}&per_page=100&page=N, including PR summaries returned there. Filter title/body by normalized keywords and the presence of pull_request for type. Do not expose arbitrary GitHub search syntax or organization-wide search. Return matched numbers, type, title, state, updated_at and match rationale as evidence. Traverse the bounded pages even when an early page has no match; preserve complete=false/continuation if capped. A summary is not a full Issue read; collector requests github_issue for relevant detail. A subsequent issue can change independently of code SHA; retain its fetch time/hash and updated_at.
- Build paths by quoting individual components. Reject invalid repository syntax, traversal, unexpected keys, binary/oversized content with typed errors.
- First 401 refreshes the installation token once and repeats the read. A second 401 returns SOURCE_APP_AUTH_FAILED. 403 returns SOURCE_ACCESS_DENIED; 404 SOURCE_NOT_FOUND (do not claim the object cannot exist); 429 returns SOURCE_RATE_LIMITED with retry_after.
- Collect all required pages inside the configured cap. If capped, complete=false and retain a continuation marker; never silently return the first page as complete.

- [ ] **Step 4: Run green**
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_github_reader.py -q`
Expected: PASS after implementation.
Add a two-page comment test, PR files/review-comment pagination, related work filtering within one repo, bounded search with incomplete empty result, truncated-tree test, 401 refresh-once test, bad ref/path test and no-token-in-errors test. Assert no git/subprocess invocation.
- [ ] **Step 5: Commit**
```powershell
git add langflow/adlc/source_access tests/unit/adlc/source_access/test_github_reader.py
git commit -m "feat: read GitHub code and issue evidence remotely"
```

### Task A4: Lark conversations, Base records and linked documents

**Files:** Create source_access/lark_messages.py, lark_base.py; test_lark_readers.py.
**Interfaces:** LarkMessageReader(client, tokens).read(ref) -> Evidence; LarkBaseReader(client, tokens).read(ref) -> Evidence. SourceGateway maps lark_document to the latter. Extract the shared HTTP helper and page walker into source_access/http.py; import SourceError there and in both readers. Reuse make_evidence and the same bounded HTTP error mapping from A3, extracted into source_access/http.py when shared.

- [ ] **Step 1: Write red**
```python
import asyncio
import httpx
from langflow.adlc.source_access.lark_messages import LarkMessageReader
from langflow.adlc.source_access.models import SourceRef

def test_thread_reads_all_pages_using_thread_container():
    seen = []
    class Tokens:
        async def get(self, force=False):
            return "tenant-test"
    def respond(request):
        seen.append(request)
        more = "page_token" not in request.url.params
        return httpx.Response(200, json={"code": 0, "data": {
            "items": [{"message_id": "m1" if more else "m2", "body": {"content": "{}"}}],
            "has_more": more, "page_token": "page2" if more else ""}})
    async def scenario():
        async with httpx.AsyncClient(base_url="https://open.larksuite.com",
                                     transport=httpx.MockTransport(respond)) as client:
            evidence = await LarkMessageReader(client, Tokens()).read(
                SourceRef(kind="lark_thread", connection_id="lark",
                          resource_id="chat1", locator={"thread_id": "thread1"}))
            assert "m1" in evidence.body and "m2" in evidence.body
            assert evidence.complete
    asyncio.run(scenario())
    assert len(seen) == 2
    assert all(r.url.params["container_id_type"] == "thread" for r in seen)
```
- [ ] **Step 2: Run red** Expected missing LarkMessageReader.
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_lark_readers.py -q`
Expected: FAIL before implementation; missing the new component or its contract.

- [ ] **Step 3: Implement exact read rules**
Use one shared page walker with this complete algorithm:
```python
async def lark_pages(fetch_page, *, max_pages=20):
    items, cursor = [], None
    for _ in range(max_pages):
        payload = await fetch_page(cursor)
        if payload.get("code") != 0:
            raise SourceError("SOURCE_LARK_READ_FAILED")
        data = payload["data"]
        items.extend(data.get("items", []))
        if not data.get("has_more", False):
            return items, True, None
        next_cursor = data.get("page_token")
        if not next_cursor or next_cursor == cursor:
            raise SourceError("SOURCE_PAGINATION_INVALID")
        cursor = next_cursor
    return items, False, cursor
```
Import SourceError from models.py. Implement:
- Messenger: resource_id is authorized chat_id. Locator permits thread_id or start_time/end_time. For thread, first resolve a message/thread descriptor within the bound chat and verify returned chat_id equals resource_id, then GET /open-apis/im/v1/messages with container_id_type=thread, container_id=thread_id. For a chat use container_id_type=chat and time bounds. Thread API does not accept time ranges; filter after retrieval and preserve root/reply IDs. Error on chat mismatch.
- Base: resource_id is app_token. Locator permits table_id, record_id or a bounded search filter serialized as JSON. Read fields before records using /bitable/v1/apps/{app_token}/tables/{table_id}/fields and /records/search; a direct record uses /records/{record_id}. Include field names/types plus returned cells. Validate filters against the authorized table/field configuration; views are filters, not authorization boundaries.
- Docx: resource_id is an explicitly granted document ID, GET /docx/v1/documents/{id}/raw_content; use blocks when structure is required. A Wiki link first resolves obj_token/type using the Wiki node API and must pass policy again for the actual object.
- Attachment cells retain a typed reference; download through the exact message-resource/media API only after grant validation. If bytes cannot be parsed with an installed parser, return metadata plus incomplete=true and a clear unsupported-format finding. Do not claim extracted text.
- Every response uses tenant app authentication. No user-token fallback. App not in chat, Base collaborator denial and linked-document denial return explicit access findings.
- Data revision uses available updated/revision IDs and body hash; preserve pagination completeness.

- [ ] **Step 4: Run green and integration tests**
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_lark_readers.py -q`
Expected: PASS after implementation.
Add Base schema+record tests, document-link denial, cross-chat thread denial, pagination cap/cycle, revoked access and binary attachment incompleteness. Mock APIs; do not access a tenant.
- [ ] **Step 5: Commit**
```powershell
git add langflow/adlc/source_access tests/unit/adlc/source_access/test_lark_readers.py
git commit -m "feat: collect scoped Lark conversation and Base context"
```

### Task A5: Wiring, operator configuration and acceptance boundary

**Files:** Complete source_access/settings.py and __init__.py; create docs/operations/source-access.md; update .env.example; tests/unit/adlc/source_access/test_settings.py.

**Interfaces:** build_source_gateway(settings, secret_resolver, http_factory) -> SourceGateway; resolve_project_grant(principal_id, project_id, run_id, settings) -> SourceGrant. Both are consumed by Plan B; their arguments are server-owned. Re-resolve the grant from current settings on every batch, retaining the persisted run budget; a revoked binding cannot be kept alive by an old run.

- [ ] **Step 1: Write red**
```python
import pytest
from langflow.adlc.source_access.settings import resolve_project_grant
from langflow.adlc.source_access.models import SourceError

def test_unknown_project_cannot_borrow_connection():
    with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
        resolve_project_grant("normalizer", "other", "run1",
            {"projects": {"p1": {"principals": ["normalizer"], "resources": {"gh": ["org/repo"]}}}})
```
- [ ] **Step 2: Run red** Missing settings function.
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_settings.py -q`
Expected: FAIL before implementation; missing the new component or its contract.
- [ ] **Step 3: Implement wiring and config**
```python
def resolve_project_grant(principal_id, project_id, run_id, settings):
    row = settings.get("projects", {}).get(project_id)
    if row is None or principal_id not in row["principals"]:
        raise SourceError("SOURCE_SCOPE_DENIED")
    return SourceGrant(project_id=project_id, run_id=run_id, principal_id=principal_id,
        resources={k: frozenset(v) for k, v in row["resources"].items()},
        locator_allowlists=row.get("locator_allowlists", {}),
        max_reads=row.get("max_reads", 24), max_bytes=row.get("max_bytes", 500_000))
```
For project-specific table restrictions, row.locator_allowlists maps "connection_id:resource_id" to allowed locator values; e.g. {"lark:base1":{"table_id":["tbl1"]}}. SourceGrant carries this map, and authorize rejects a missing/disallowed constrained locator before I/O. Re-resolve it for every batch. No per-project restriction is stored in a shared reader singleton. Field-level restrictions require query projection plus response redaction of fields and schema before evidence construction; if unsupported by the selected endpoint/reader, reject that configuration with SOURCE_FIELD_SCOPE_UNSUPPORTED rather than leaking fields. Do not claim a view/filter is an access-control boundary. A server-declared document alias (including Wiki node) must resolve to a separately authorized document ID. Do not treat a record link as a permission grant.

build_source_gateway creates one connection's app-token provider and the matching readers from A2-A4. Reject unknown provider kinds and absent required secret references with SOURCE_CONNECTION_UNAVAILABLE. Each client has fixed origin, timeout=15, redirects disabled and no ambient personal credential lookup.
Add only these non-secret example settings:
```dotenv
ADLC_SOURCE_BINDINGS_FILE=
ADLC_SOURCE_MAX_READS=24
ADLC_SOURCE_MAX_BYTES=500000
```
The operator file contains project/principal/resource bindings and secret reference names, never committed secret values. Document GitHub App selected-repo installation, Lark app approval, bot membership, Base collaborator and linked-document access. Token rotation happens without changing project binding IDs. The normalizer supplies source IDs; it cannot set permission grants.

- [ ] **Step 4: Verify**
Run: `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access/test_settings.py -q`
Expected: PASS after implementation.
Run `.venv\Scripts\python.exe -m pytest --confcutdir=tests/unit/adlc/source_access tests/unit/adlc/source_access -q` for the complete source_access suite. Smoke-check against dedicated app-owned fixtures only after operator provisioning; record actual source IDs, versions and outcomes without credentials. Expected live results: one GitHub file+Issue/comments, one full Lark thread, one Base record+granted linked document; a denied project must fail before I/O. Fake-test success is not a live acceptance claim.
- [ ] **Step 5: Commit**
```powershell
git add langflow/adlc/source_access tests/unit/adlc/source_access ../docs/operations/source-access.md ../.env.example
git commit -m "docs: configure application-owned source access"
```

## Self-review and handoff

Coverage: GitHub code/Issue/PR/related work A3; Messenger/Base/documents A4; identity and refresh A2; server-owned permissions/budgets A1/A5. A1-A5 expose the exact SourceGateway/SourceGrant/SourceRef/Evidence port consumed by Plan B. No personal token or local clone path is part of that port.

Run formatting and focused tests once after the final change; repeat only after a new failure/change. Install no native specification framework as part of this source-only plan.

Plan B: docs/superpowers/plans/2026-11-25-requirement-readiness-pipeline.md.
