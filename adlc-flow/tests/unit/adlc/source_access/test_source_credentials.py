# ruff: noqa: INP001, S101
import asyncio
import json
from datetime import datetime, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from langflow.adlc.source_access.credentials import GitHubAppTokens, LarkTenantTokens
from langflow.adlc.source_access.models import SourceError
from langflow.adlc.source_access.settings import ConnectionSettings

LARK = "https://open.larksuite.com"
GITHUB = "https://api.github.com"
AUTH_FAILED = "SOURCE_APP_AUTH_FAILED"


def mock_client(origin, respond, **options):
    return httpx.AsyncClient(base_url=origin, transport=httpx.MockTransport(respond), trust_env=False, **options)


def lark_response(value="fake-app-token", ttl=7200):
    return httpx.Response(200, json={"code": 0, "msg": "ok", "tenant_access_token": value, "expire": ttl})


@pytest.mark.parametrize("origin", [LARK, LARK + "/"])
def test_lark_uses_app_secret_and_caches_token(origin):
    requests = []

    def respond(request):
        requests.append(request)
        return lark_response()

    async def scenario():
        async with mock_client(origin, respond, headers={"Authorization": "Bearer personal-token"}) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: 1000)
            assert await tokens.get() == await tokens.get() == "fake-app-token"

    asyncio.run(scenario())
    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == f"{LARK}/open-apis/auth/v3/tenant_access_token/internal"
    assert json.loads(request.content) == {"app_id": "app", "app_secret": "test-secret"}
    assert "authorization" not in request.headers


def test_refreshes_at_sixty_seconds_remaining():
    now = 1000
    responses = iter([lark_response("first", 120), lark_response("refreshed", 120)])

    async def scenario():
        nonlocal now
        async with mock_client(LARK, lambda _: next(responses)) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: now)
            assert await tokens.get() == "first"
            now = 1059
            assert await tokens.get() == "first"
            now = 1060
            assert await tokens.get() == "refreshed"

    asyncio.run(scenario())


def test_force_refreshes_token_with_time_remaining():
    responses = iter([lark_response("first"), lark_response("refreshed")])

    async def scenario():
        async with mock_client(LARK, lambda _: next(responses)) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: 1000)
            assert await tokens.get() == "first"
            assert await tokens.get(force=True) == "refreshed"
            assert await tokens.get() == "refreshed"

    asyncio.run(scenario())


def test_failed_force_refresh_does_not_reuse_previous_token():
    responses = iter([lark_response("first"), httpx.Response(401), lark_response("replacement")])

    async def scenario():
        async with mock_client(LARK, lambda _: next(responses)) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: 1000)
            assert await tokens.get() == "first"
            with pytest.raises(SourceError, match=AUTH_FAILED):
                await tokens.get(force=True)
            assert await tokens.get() == "replacement"

    asyncio.run(scenario())


def test_concurrent_requests_share_one_refresh():
    async def scenario():
        exchange_entered = asyncio.Event()
        release_exchange = asyncio.Event()
        requests = []

        async def respond(request):
            requests.append(request)
            exchange_entered.set()
            await release_exchange.wait()
            return lark_response()

        async with mock_client(LARK, respond) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: 1000)
            first = asyncio.create_task(tokens.get())
            await exchange_entered.wait()
            callers_entered = asyncio.Event()
            waiting = 0
            concurrent_callers = 4

            async def concurrent_get():
                nonlocal waiting
                waiting += 1
                if waiting == concurrent_callers:
                    callers_entered.set()
                return await tokens.get()

            followers = [asyncio.create_task(concurrent_get()) for _ in range(concurrent_callers)]
            await callers_entered.wait()
            release_exchange.set()
            assert await asyncio.gather(first, *followers) == ["fake-app-token"] * 5
        assert len(requests) == 1

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="raw-response-secret", headers={"content-type": "application/json"}),
        httpx.Response(200, json=["raw-response-secret"]),
        httpx.Response(200, json={"code": 0, "tenant_access_token": "raw-response-secret"}),
        httpx.Response(200, json={"code": 0, "expire": 7200}),
        lark_response(""),
        lark_response("raw-response-secret", 0),
        lark_response("raw-response-secret", -1),
        lark_response("raw-response-secret", ttl=True),
        lark_response("raw-response-secret", "not-a-duration"),
        pytest.param(lark_response("raw-response-secret", 10**309), id="oversized-ttl"),
        httpx.Response(200, json={"code": False, "tenant_access_token": "raw-response-secret", "expire": 7200}),
        httpx.Response(200, json={"code": 10003, "msg": "raw-response-secret"}),
        httpx.Response(401, text="raw-response-secret"),
        httpx.Response(307, headers={"Location": "https://untrusted.invalid/raw-response-secret"}),
    ],
)
def test_lark_rejects_malformed_or_rejected_auth_without_exposing_provider_data(response):
    requests = []

    def respond(request):
        requests.append(request)
        return response

    async def scenario():
        async with mock_client(LARK, respond) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: 1000)
            with pytest.raises(SourceError) as failure:
                await tokens.get()
            assert str(failure.value) == AUTH_FAILED
            assert failure.value.__context__ is None

    asyncio.run(scenario())
    assert len(requests) == 1


def test_network_error_is_sanitized():
    def respond(request):
        msg = "upstream-network-secret"
        raise httpx.ConnectError(msg, request=request)

    async def scenario():
        async with mock_client(LARK, respond) as client:
            tokens = LarkTenantTokens(client, "app", "test-secret", clock=lambda: 1000)
            with pytest.raises(SourceError) as failure:
                await tokens.get()
            assert str(failure.value) == AUTH_FAILED
            assert failure.value.__context__ is None

    asyncio.run(scenario())


@pytest.fixture(scope="module")
def github_signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return private_pem, key.public_key()


def test_github_requests_read_only_installation_token_with_short_lived_app_jwt(github_signing_key):
    private_key, public_key = github_signing_key
    now = 1_700_000_000
    expires_at = datetime.fromtimestamp(now + 3600, timezone.utc).isoformat().replace("+00:00", "Z")

    def respond(request):
        assert request.method == "POST"
        assert request.headers["User-Agent"] == "PokeDev"
        assert str(request.url) == f"{GITHUB}/app/installations/42/access_tokens"
        scheme, token = request.headers["Authorization"].split(" ")
        assert scheme == "Bearer"
        claims = jwt.decode(token, public_key, algorithms=["RS256"], issuer="123", options={"verify_exp": False})
        assert claims == {"iat": now - 60, "exp": now + 540, "iss": "123"}
        max_jwt_lifetime_seconds = 600
        assert claims["exp"] - claims["iat"] <= max_jwt_lifetime_seconds
        assert json.loads(request.content) == {
            "permissions": {"contents": "read", "issues": "read", "pull_requests": "read"}
        }
        return httpx.Response(201, json={"token": "installation-token", "expires_at": expires_at})

    async def scenario():
        async with mock_client(GITHUB, respond, auth=("personal-account", "personal-token")) as client:
            tokens = GitHubAppTokens(client, "123", private_key, "42", clock=lambda: now)
            assert await tokens.get() == "installation-token"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, json={"token": "provider-secret", "expires_at": "provider-secret"}),
        httpx.Response(201, json={"token": "provider-secret", "expires_at": "2099-01-01T00:00:00"}),
        httpx.Response(201, json={"token": "provider-secret", "expires_at": "1970-01-01T00:16:40Z"}),
        httpx.Response(201, json={"expires_at": "2099-01-01T00:00:00Z"}),
        httpx.Response(403, text="provider-secret"),
    ],
)
def test_github_sanitizes_malformed_or_rejected_auth(github_signing_key, response):
    private_key, _ = github_signing_key

    async def scenario():
        async with mock_client(GITHUB, lambda _: response) as client:
            tokens = GitHubAppTokens(client, "123", private_key, "42", clock=lambda: 1000)
            with pytest.raises(SourceError) as failure:
                await tokens.get()
            assert str(failure.value) == AUTH_FAILED
            assert failure.value.__context__ is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("key_kind", "installation"),
    [("malformed", "42"), ("public", "42"), ("private", "42/../99")],
)
def test_github_rejects_invalid_signing_key_or_installation_before_network(github_signing_key, key_kind, installation):
    private_key, public_key = github_signing_key
    key = {
        "malformed": b"private-key-secret",
        "public": public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo),
        "private": private_key,
    }[key_kind]

    async def scenario():
        async with mock_client(GITHUB, lambda _: pytest.fail("unexpected network request")) as client:
            tokens = GitHubAppTokens(client, "123", key, installation, clock=lambda: 1000)
            with pytest.raises(SourceError) as failure:
                await tokens.get()
            assert str(failure.value) == AUTH_FAILED
            assert failure.value.__context__ is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("base_url", "trust_env", "follow_redirects"),
    [
        ("https://open.larksuite.com.untrusted.invalid", False, False),
        ("http://open.larksuite.com", False, False),
        ("https://open.larksuite.com:9443", False, False),
        ("https://open.larksuite.com/untrusted", False, False),
        ("https://user:credential@open.larksuite.com", False, False),
        (GITHUB, False, False),
        (LARK, True, False),
        (LARK, False, True),
    ],
)
def test_rejects_unsafe_exchange_client_at_construction(base_url, trust_env, follow_redirects):
    async def scenario():
        async with httpx.AsyncClient(
            base_url=base_url,
            trust_env=trust_env,
            follow_redirects=follow_redirects,
            transport=httpx.MockTransport(lambda _: pytest.fail("unexpected network request")),
        ) as client:
            with pytest.raises(SourceError, match=AUTH_FAILED):
                LarkTenantTokens(client, "app", "test-secret")

    asyncio.run(scenario())


def test_connection_settings_hold_only_identity_and_secret_references():
    settings = ConnectionSettings(
        connection_id="company-github",
        provider="github",
        app_id="123",
        private_key_secret_ref="key-ref",  # noqa: S106
        installation_id="42",
    )
    assert settings.model_dump(exclude_none=True) == {
        "connection_id": "company-github",
        "provider": "github",
        "app_id": "123",
        "private_key_secret_ref": "key-ref",
        "installation_id": "42",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"connection_id": "team:lark"},
        {"app_id": ""},
        {"app_secret_ref": None},
        {"app_secret_ref": " "},
        {"tenant_id": None},
        {"private_key_secret_ref": "unexpected-key-reference"},
        {"installation_id": "42"},
        {"app_secret": "unexpected-raw-secret"},
    ],
)
def test_lark_connection_settings_reject_invalid_or_mixed_credentials(overrides):
    values = {
        "connection_id": "team-lark",
        "provider": "lark",
        "app_id": "cli_app",
        "app_secret_ref": "APP_SECRET_REF",
        "tenant_id": "team",
    }
    with pytest.raises(ValidationError):
        ConnectionSettings(**(values | overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"installation_id": None},
        {"installation_id": "42/99"},
        {"installation_id": "0"},
        {"private_key_secret_ref": None},
        {"app_secret_ref": "unexpected-app-secret-reference"},
        {"tenant_id": "team"},
    ],
)
def test_github_connection_settings_reject_invalid_or_mixed_credentials(overrides):
    values = {
        "connection_id": "company-github",
        "provider": "github",
        "app_id": "123",
        "installation_id": "42",
        "private_key_secret_ref": "PRIVATE_KEY_REF",
    }
    with pytest.raises(ValidationError):
        ConnectionSettings(**(values | overrides))
