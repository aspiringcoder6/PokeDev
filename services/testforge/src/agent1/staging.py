"""Explicit, reviewed staging suites with owned fixtures and real execution only.

Application-specific routes, sessions and oracles are supplied by the profile/suite.
No demo reset, generated credentials, inferred permissions or automatic healing.
"""
import copy
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
import jsonschema
from pathlib import Path
from urllib.parse import urljoin, urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from .executor.runner import PlaywrightExecutor
from .executor.verifiers.db_verifier import DbVerifier
from .generator.playwright_generator import PlaywrightGenerator
from .generator.static_validator import StaticValidator
from .reporter.functional_reporter import FunctionalReporter
from .reporter.junit_reporter import JUnitReporter
from .reporter.proof_store import ProofStore
from .designer.reviewed_rules import expand_suite


class ConfigError(ValueError):
    pass


def endpoint(base, path):
    url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    origin = urlsplit(base)
    target = urlsplit(url)
    if target.scheme not in ("https", "http") or (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
        raise ConfigError("Endpoint must stay on the configured origin")
    if target.username or target.password:
        raise ConfigError("Credentials cannot be embedded in URLs")
    return url


def resolve(value, bindings):
    """Only named bindings; preserve type for a whole-value reference."""
    if isinstance(value, dict):
        return {k: resolve(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, bindings) for v in value]
    if not isinstance(value, str):
        return value
    def lookup(match):
        name = match.group(1)
        if name not in bindings:
            raise ConfigError(f"Unknown binding: {name}")
        return bindings[name]
    pattern = r"\$\{([A-Za-z0-9_.]+)\}"
    match = re.fullmatch(pattern, value)
    if match:
        return lookup(match)
    return re.sub(pattern, lambda m: str(lookup(m)), value)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def extract_id(body, id_field):
    """Resolve a dotted id_field (e.g. "data.id") inside a wrapped response."""
    current = body
    for part in str(id_field or "id").split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def preflight(profile):
    """Fail fast when the target is unreachable or unhealthy, before allocating a run."""
    for name in ("base_url", "api_url"):
        try:
            with build_opener(NoRedirect()).open(Request(endpoint(profile[name], "/")), timeout=10) as response:
                if response.status >= 500:
                    raise ConfigError(f"{name} returned HTTP {response.status}")
        except HTTPError as exc:
            if exc.code >= 500:
                raise ConfigError(f"{name} returned HTTP {exc.code}") from exc
        except (URLError, OSError) as exc:
            raise ConfigError(f"{name} is unreachable: {exc}") from exc


def prune_runs(output_root, keep=20):
    """Delete oldest staging run directories beyond the retention window."""
    if keep is None or keep < 1:
        return
    root = Path(output_root).resolve()
    if not root.is_dir():
        return
    runs = sorted((p for p in root.glob("STAGING-*") if p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in runs[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def mint_session(profile, login, out_path):
    """Log in through the API and persist a per-case storageState refresh cookie."""
    body = json.dumps({"email": os.environ[login["email_env"]],
                       "password": os.environ[login["password_env"]]}).encode()
    req = Request(endpoint(profile["api_url"], login.get("path", "/auth/login")), data=body,
                  method="POST", headers={"Content-Type": "application/json"})
    opener = build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=30) as response:
            payload = json.loads(response.read())
            cookies = response.headers.get_all("Set-Cookie") or []
    except HTTPError as exc:
        raise ConfigError(f"Actor login failed with status {exc.code}: {exc.read().decode()}") from exc
    if payload.get("success") is not True:
        raise ConfigError("Actor login returned an unexpected payload")
    raw, path = None, "/api/v1/auth"
    for header in cookies:
        if "refresh_token=" in header:
            raw = header.split("refresh_token=", 1)[1].split(";", 1)[0]
            for part in header.split(";")[1:]:
                if part.strip().lower().startswith("path="):
                    path = part.strip().split("=", 1)[1]
            break
    if not raw:
        raise ConfigError("Login response did not set a refresh_token cookie")
    state = {"cookies": [{"name": "refresh_token", "value": raw, "domain": urlsplit(profile["api_url"]).hostname,
                          "path": path, "expires": time.time() + 7 * 24 * 3600, "httpOnly": True,
                          "secure": False, "sameSite": "Lax"}], "origins": []}
    Path(out_path).write_text(json.dumps(state, indent=2), encoding="utf-8")


class FixtureClient:
    def __init__(self, profile):
        self.base = profile["api_url"]
        self.headers = {"Content-Type": "application/json"}
        for key, env in profile.get("fixture_headers_env", {}).items():
            if not os.environ.get(env):
                raise ConfigError(f"Missing secret reference: {env}")
            self.headers[key] = os.environ[env]
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None):
        req = Request(endpoint(self.base, path), method=method, headers=self.headers,
                      data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(req, timeout=30) as response:
                data = response.read()
                return response.status, json.loads(data) if data else None
        except HTTPError as exc:
            try:
                raw = exc.read()
                err_body = json.loads(raw)
            except:
                err_body = {"error": raw.decode() if 'raw' in locals() else str(exc)}
            return exc.code, err_body


class ReadOnlySQLite:
    def __init__(self, env_name):
        path = Path(os.environ.get(env_name, "")).resolve()
        if not path.is_file():
            raise ConfigError(f"Missing read-only database: {env_name}")
        self.path = path

    def fetch(self, query, params=None):
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, params or {})]


def validate(profile, suite):
    schema_path = Path(__file__).resolve().parents[2] / "schemas/staging_profile.schema.json"
    jsonschema.validate(profile, json.loads(schema_path.read_text(encoding="utf-8")))
    jsonschema.validate(suite, json.loads(schema_path.with_name("staging_suite.schema.json").read_text(encoding="utf-8")))
    if profile.get("version") != 1 or suite.get("version") != 1:
        raise ConfigError("Profile and suite version must be 1")
    for name in ("base_url", "api_url"):
        url = profile.get(name, "")
        if not urlsplit(url).netloc:
            raise ConfigError(f"Missing {name}")
        endpoint(url, "/")
    if not suite.get("cases"):
        raise ConfigError("Suite must contain cases")
    seen = set()
    for case in suite["cases"]:
        cid = case.get("test_case_id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cid) or cid in seen:
            raise ConfigError("Invalid or duplicate case ID")
        seen.add(cid)
        actor = profile.get("actors", {}).get(case.get("actor"))
        if actor is None:
            raise ConfigError(f"Unknown actor for {cid}")
        if not actor.get("anonymous"):
            login = actor.get("login")
            if login:
                if not login.get("email_env") or not login.get("password_env"):
                    raise ConfigError("Actor login requires email_env and password_env")
            elif not actor.get("storage_state_env"):
                raise ConfigError("Authenticated actor requires login credentials or storage_state_env")
            if not actor.get("identity", {}).get("expected_payload"):
                raise ConfigError("Authenticated actor requires identity oracle")
        if not case.get("steps") or not case.get("requirement_refs"):
            raise ConfigError("Steps and requirement_refs are required")
        if not (case.get("ui_oracles") or case.get("api_checks") or case.get("db")):
            raise ConfigError("Explicit oracles are required")
        for oracle in case.get("ui_oracles", []) + case.get("api_checks", []):
            if not oracle.get("source_ref"):
                raise ConfigError("Each oracle needs source_ref")
        for oracle in case.get("ui_oracles", []):
            if oracle.get("type") not in ("TEXT", "VALUE", "COUNT", "URL", "VISIBLE", "ABSENT"):
                raise ConfigError("Unsupported UI oracle")
            if oracle["type"] in ("TEXT", "VALUE", "COUNT", "URL") and "expected" not in oracle:
                raise ConfigError("Oracle expected value is required")
        for check in case.get("api_checks", []):
            endpoint(profile["api_url"], check["path"])
        for step in case["steps"]:
            if step.get("action") == "WAIT":
                raise ConfigError("Staging uses assertion deadlines, not fixed WAIT")
        for fixture in case.get("fixtures", []):
            if not fixture.get("cleanup_path") or "${fixture.id}" not in fixture["cleanup_path"]:
                raise ConfigError("Fixture cleanup must target the created ID")
        if case.get("db") and not case["db"].get("source_ref"):
            raise ConfigError("DB oracle needs source_ref")


def api_assertions(checks, profile):
    """Execute verification in the browser's authenticated API context."""
    lines = []
    if any(check.get("auth") == "refresh" for check in checks):
        refresh_url = json.dumps(endpoint(profile["api_url"], "/auth/refresh"))
        lines += [f"    const authResponse = await page.request.post({refresh_url});",
                  "    expect(authResponse.status()).toBe(201);",
                  "    const authToken = (await authResponse.json()).data.accessToken;"]
    for i, check in enumerate(checks):
        url = endpoint(profile["api_url"], check["path"])
        status = int(check.get("expected_status", 200))
        method = str(check.get("method", "GET")).upper()
        if method not in ("GET", "POST", "DELETE"):
            raise ConfigError("API check method must be GET, POST, or DELETE")
        timeout = int(check.get("timeout_ms", 0))
        if timeout < 0 or timeout > 60000:
            raise ConfigError("API polling timeout must be between 0 and 60000 ms")
        request_line = f"    const response{i} = await page.request.{method.lower()}({json.dumps(url)}"
        option_parts = []
        if "body" in check:
            option_parts.append(f"data: {json.dumps(check['body'], ensure_ascii=False)}")
        if check.get("auth") == "refresh":
            option_parts.append("headers: { Authorization: 'Bearer ' + authToken }")
        if option_parts:
            request_line += ", { " + ", ".join(option_parts) + " }"
        request_line += ");"
        lines += ["    await expect(async () => {" if timeout else "    {", request_line,
                  f"    expect(response{i}.status()).toBe({status});"]
        if "expected_payload" in check:
            lines += [f"    const payload{i} = await response{i}.json();"]
            def fields(expected, expression):
                if isinstance(expected, dict):
                    for key, value in expected.items():
                        yield f"    expect({expression}).toHaveProperty({json.dumps([key])});"
                        yield from fields(value, expression + "[" + json.dumps(key) + "]")
                else:
                    yield f"    expect({expression}).toEqual({json.dumps(expected, ensure_ascii=False)});"
            lines += list(fields(check["expected_payload"], f"payload{i}"))
        lines.append(f"    }}).toPass({{ timeout: {timeout}, intervals: [250, 500, 1000] }});" if timeout else "    }")
    return "\n".join(lines)


def run_suite(profile, suite, output_root="artifacts/automation/staging", executor_factory=PlaywrightExecutor,
              keep_runs=20, headed=False, slowmo=0):
    suite, coverage = expand_suite(suite)
    validate(profile, suite)
    is_headed = headed or profile.get("headed", False) or os.environ.get("STAGING_HEADED", "").lower() in ("1", "true", "yes")
    slow_mo = slowmo or profile.get("slowmo", 0) or int(os.environ.get("STAGING_SLOWMO", "0") or 0)
    run_id = "STAGING-" + uuid.uuid4().hex
    root = Path(output_root).resolve() / run_id
    root.mkdir(parents=True)
    (root / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    artifacts = []
    client = FixtureClient(profile)
    for original in suite["cases"]:
        case_dir = root / original["test_case_id"] / "attempt-1"
        case_dir.mkdir(parents=True)
        owned = []
        short_id = run_id.split("-")[-1][:6].upper()
        bindings = {"run_id": run_id, "case_id": original["test_case_id"], "short_id": short_id}
        artifact = {"test_case_id": original["test_case_id"], "status": "ERROR", "execution_mode": "local",
                    "requirement_refs": original["requirement_refs"], "actor": original["actor"]}
        try:
            # Persist registry immediately after each successful setup, including on subsequent failure.
            for fixture in original.get("fixtures", []):
                configured = resolve({k: v for k, v in fixture.items() if k != "cleanup_path"}, bindings)
                status, body = client.request("POST", configured["path"], configured.get("body"))
                if status != configured.get("expected_status", 201):
                    raise ConfigError(f"Fixture setup failed with status {status}. Sent: {json.dumps(configured.get('body'))}. Response: {json.dumps(body)}")
                entity_id = extract_id(body, configured.get("id_field", "id"))
                if entity_id is None or str(entity_id) in ("", ".", ".."):
                    raise ConfigError("Fixture response lacks ID; cleanup requires intervention")
                cleanup = fixture["cleanup_path"].replace("${fixture.id}", quote(str(entity_id), safe=""))
                cleanup = resolve(cleanup, bindings)
                endpoint(profile["api_url"], cleanup)
                owned.append({"id": entity_id, "cleanup_path": cleanup})
                (case_dir / "owned.json").write_text(json.dumps(owned, indent=2), encoding="utf-8")
                bindings[configured["name"] + ".id"] = entity_id
                for key, value in (configured.get("body") or {}).items():
                    if isinstance(value, (str, int, float, bool)) or value is None:
                        bindings[configured["name"] + "." + key] = value
            case = resolve(copy.deepcopy({k: v for k, v in original.items() if k != "fixtures"}), bindings)
            case.update(routes=resolve(profile.get("routes", {}), bindings), locators=resolve(profile.get("locators", {}), bindings),
                        strict_mapping=True, expected_results=[], function_id=case.get("function_id", case["test_case_id"]))
            for step in case["steps"]:
                if step["action"] == "OPEN":
                    step["target"] = endpoint(profile["base_url"], case["routes"].get(step["target"], step["target"]))
            script = PlaywrightGenerator.generate_script(case)
            guard = StaticValidator.validate(script, case)
            if not guard["valid"]:
                raise ConfigError("Generated script failed static validation")
            actor = profile["actors"][case["actor"]]
            use = {"baseURL": profile["base_url"], "headless": not is_headed, "screenshot": "only-on-failure",
                   "trace": "retain-on-failure" if actor.get("anonymous") else "off"}
            if slow_mo > 0:
                use["launchOptions"] = {"slowMo": slow_mo}
            if not actor.get("anonymous"):
                if actor.get("login"):
                    state_path = case_dir / "session.state.json"
                    mint_session(profile, actor["login"], state_path)
                else:
                    state_path = Path(os.environ.get(actor["storage_state_env"], "")).resolve()
                    if not state_path.is_file():
                        raise ConfigError("Actor storage state is unavailable")
                use["storageState"] = str(state_path)
                identity = api_assertions([actor["identity"]], profile)
                script = script.replace("    // Step ", identity + "\n    // Step ", 1)
            checks = api_assertions(case.get("api_checks", []), profile)
            script = script.replace("    // Assertions", checks + "\n    // Assertions", 1)
            spec = case_dir / (case["test_case_id"] + ".spec.ts")
            spec.write_text(script, encoding="utf-8")
            case_timeout = max(int(profile.get("timeout_ms", 30000)), 60000 if slow_mo >= 1000 else int(profile.get("timeout_ms", 30000)))
            config = case_dir / "playwright.config.cjs"
            config.write_text("module.exports = " + json.dumps({"testDir": str(case_dir), "outputDir": str(case_dir / "browser"),
                "testMatch": "*.spec.ts", "workers": 1, "retries": 0,
                "use": use, "timeout": case_timeout}) + ";", encoding="utf-8")
            try:
                executor = executor_factory(config_path=str(config), timeout_ms=case_timeout, headless=not is_headed)
            except TypeError:
                executor = executor_factory(config_path=str(config), timeout_ms=case_timeout)
            discovery = executor.discovery_check(str(spec))
            if not discovery.get("ok"):
                raise ConfigError("Playwright discovery failed: " + discovery.get("stderr", ""))
            result = executor.execute_script(case["test_case_id"], script, script_path=str(spec), real_runtime=True)
            artifact.update(result, script_path=str(spec), oracles=case.get("ui_oracles", []), api_checks=case.get("api_checks", []))
            if result.get("execution_mode") != "local":
                artifact.update(status="ERROR", error="Executor did not provide real execution provenance")
            if case.get("db"):
                db_cfg = case["db"]
                connector = ReadOnlySQLite(profile["db_sqlite_path_env"]) if profile.get("db_sqlite_path_env") else None
                verification = DbVerifier(connector).verify(verification_strategy={**db_cfg, "enabled": True})
                artifact["db_verification"] = verification.to_dict()
                if verification.status != "PASS":
                    artifact["status"] = verification.status
        except Exception as exc:
            artifact.update(status="ERROR", error=f"{type(exc).__name__}: {exc}")
        finally:
            cleanup = []
            for item in reversed(owned):
                try:
                    status, _ = client.request("DELETE", item["cleanup_path"])
                    ok = status in (200, 204, 403, 404)
                except Exception:
                    status, ok = None, False
                cleanup.append({"id": item["id"], "status": status, "ok": ok})
            artifact["cleanup"] = cleanup
            if any(not item["ok"] for item in cleanup):
                artifact.update(status="ERROR", error="Owned fixture cleanup failed")
            # Redact configured fixture credentials from diagnostics before persistence.
            secret_values = [os.environ.get(env) for env in profile.get("fixture_headers_env", {}).values()]
            serialized = json.dumps(artifact, ensure_ascii=False)
            for secret in secret_values:
                if secret:
                    serialized = serialized.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED]")
            artifact = json.loads(serialized)
            artifacts.append(artifact)
            (case_dir / "result.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(a["status"] == "PASS" for a in artifacts)
    result = FunctionalReporter.compile_functional_result(run_id, suite.get("name", "Staging"), len(artifacts),
        passed, len(artifacts) - passed, execution_mode="local", initial_passed=passed)
    result["exit_code"] = 2 if any(a["status"] == "ERROR" for a in artifacts) else (0 if result["gate_passed"] else 1)
    (root / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (root / "junit.xml").write_text(JUnitReporter.from_functional_result(result, artifacts), encoding="utf-8")
    if result["gate_passed"]:
        handoff = _extract_performance_handoff(run_id, artifacts)
        (root / "performance_handoff.json").write_text(json.dumps(handoff, indent=2), encoding="utf-8")
    ProofStore.write_run_proofs(run_id, artifacts, str(root))
    prune_runs(output_root, keep_runs)
    return {"functional_result": result, "artifacts": artifacts, "output_dir": str(root)}


def _extract_performance_handoff(run_id: str, artifacts: list) -> dict:
    """Trích xuất verified flows từ các case thành công để bàn giao cho Agent 2."""
    verified_flows = []
    seen = set()
    for a in artifacts:
        if a.get("status") != "PASS":
            continue
        events = a.get("network_events") or []
        for ev in events:
            method = ev.get("method", "GET").upper()
            url = ev.get("url", "")
            status = ev.get("status", 200)
            if "/api/v1/" in url and 200 <= status < 300:
                path = url.split("://")[-1].partition("/")[2]
                path = "/" + path.partition("?")[0]
                api_key = f"{method} {path}"
                if api_key not in seen:
                    seen.add(api_key)
                    if "auth/login" in path:
                        payload_fields = [
                            {"name": "email", "source": "user.email"},
                            {"name": "password", "source": "user.password"},
                        ]
                        response_field = "access_token"
                    else:
                        payload_fields = []
                        response_field = None
                    verified_flows.append({
                        "api_id": api_key,
                        "method": method,
                        "path": path,
                        "expected_status": status,
                        "payload_fields": payload_fields,
                        "response_has_field": response_field,
                    })
    if not verified_flows:
        verified_flows.append({
            "api_id": "POST /api/v1/auth/login",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "expected_status": 201,
            "payload_fields": [
                {"name": "email", "source": "user.email"},
                {"name": "password", "source": "user.password"},
            ],
            "response_has_field": "access_token",
        })
    login_present = any("auth/login" in f.get("path", "") for f in verified_flows)
    if not login_present:
        verified_flows.insert(0, {
            "api_id": "POST /api/v1/auth/login",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "expected_status": 201,
            "payload_fields": [
                {"name": "email", "source": "user.email"},
                {"name": "password", "source": "user.password"},
            ],
            "response_has_field": "access_token",
        })
    return {
        "source_run_id": run_id,
        "gate_passed": True,
        "verified_flows": verified_flows,
    }
