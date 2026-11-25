import asyncio
import math
import re
import time
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus

import httpx
import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from .models import SourceError

GITHUB_API_ORIGIN = "https://api.github.com"
LARK_API_ORIGIN = "https://open.larksuite.com"
_AUTH_FAILED = "SOURCE_APP_AUTH_FAILED"
_REFRESH_MARGIN_SECONDS = 60


class _CachedAppTokens:
    def __init__(self, client: httpx.AsyncClient, origin: str, clock: Callable[[], float]):
        allowed_base_urls = (httpx.URL(origin), httpx.URL(origin + "/"))
        if client.base_url not in allowed_base_urls or client.trust_env or client.follow_redirects:
            raise SourceError(_AUTH_FAILED)
        self._client = client
        self._origin = origin
        self._clock = clock
        self._lock = asyncio.Lock()
        self._token = ""
        self._expires_at = 0.0

    async def get(self, force: bool = False) -> str:  # noqa: FBT001, FBT002
        async with self._lock:
            if not force and self._token and self._expires_at - self._clock() > _REFRESH_MARGIN_SECONDS:
                return self._token

            self._token = ""
            self._expires_at = 0.0
            try:
                token, expires_at = await self._fetch()
            except (
                httpx.HTTPError,
                jwt.PyJWTError,
                UnsupportedAlgorithm,
                KeyError,
                OverflowError,
                RecursionError,
                TypeError,
                ValueError,
            ):
                pass
            else:
                if (
                    isinstance(token, str)
                    and re.fullmatch(r"[!-~]+", token)
                    and math.isfinite(expires_at)
                    and expires_at > self._clock()
                ):
                    self._token = token
                    self._expires_at = expires_at
                    return token
            # Raise outside the handler so provider bodies and request headers are not chained.
            raise SourceError(_AUTH_FAILED)

    async def _post_exchange(
        self,
        path: str,
        payload: dict,
        *,
        authorization: str | None = None,
    ) -> httpx.Response:
        if self._client.is_closed:
            raise SourceError(_AUTH_FAILED)
        # An explicit request keeps default client headers, cookies and auth out of the exchange.
        headers = {"User-Agent": "PokeDev"}
        if authorization is not None:
            headers["Authorization"] = authorization
        request = httpx.Request("POST", self._origin + path, json=payload, headers=headers)
        return await self._client.send(request, auth=None, follow_redirects=False)

    async def _fetch(self) -> tuple[str, float]:
        raise NotImplementedError


class LarkTenantTokens(_CachedAppTokens):
    def __init__(
        self,
        client: httpx.AsyncClient,
        app_id: str,
        app_secret: str,
        clock: Callable[[], float] = time.time,
    ):
        super().__init__(client, LARK_API_ORIGIN, clock)
        self._app_id = app_id
        self._app_secret = app_secret

    async def _fetch(self) -> tuple[str, float]:
        requested_at = self._clock()
        response = await self._post_exchange(
            "/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self._app_id, "app_secret": self._app_secret},
        )
        if response.status_code != HTTPStatus.OK:
            raise SourceError(_AUTH_FAILED)
        data = response.json()
        if not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 0:
            raise SourceError(_AUTH_FAILED)
        ttl = data["expire"]
        if type(ttl) is not int or ttl <= 0:
            raise SourceError(_AUTH_FAILED)
        return data["tenant_access_token"], requested_at + ttl


class GitHubAppTokens(_CachedAppTokens):
    def __init__(
        self,
        client: httpx.AsyncClient,
        app_id: str,
        private_key: str | bytes,
        installation_id: str | int,
        clock: Callable[[], float] = time.time,
    ):
        super().__init__(client, GITHUB_API_ORIGIN, clock)
        self._app_id = app_id
        self._private_key = private_key
        self._installation_id = str(installation_id)

    async def _fetch(self) -> tuple[str, float]:
        if re.fullmatch(r"[1-9][0-9]*", self._installation_id) is None:
            raise SourceError(_AUTH_FAILED)
        key = self._private_key.encode() if isinstance(self._private_key, str) else self._private_key
        signing_key = load_pem_private_key(key, password=None)
        if not isinstance(signing_key, RSAPrivateKey):
            raise SourceError(_AUTH_FAILED)
        now = int(self._clock())
        signed = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self._app_id},
            signing_key,
            algorithm="RS256",
        )
        response = await self._post_exchange(
            f"/app/installations/{self._installation_id}/access_tokens",
            {"permissions": {"contents": "read", "issues": "read", "pull_requests": "read"}},
            authorization=f"Bearer {signed}",
        )
        if response.status_code != HTTPStatus.CREATED:
            raise SourceError(_AUTH_FAILED)
        data = response.json()
        expiry = data["expires_at"]
        if not isinstance(expiry, str):
            raise SourceError(_AUTH_FAILED)
        if expiry.endswith("Z"):
            expiry = expiry[:-1] + "+00:00"
        expires_at = datetime.fromisoformat(expiry)
        if expires_at.tzinfo is None:
            raise SourceError(_AUTH_FAILED)
        return data["token"], expires_at.timestamp()
