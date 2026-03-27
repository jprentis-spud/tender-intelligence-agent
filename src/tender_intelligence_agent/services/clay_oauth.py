"""Lightweight OAuth2 auth for Clay's MCP endpoint.

Handles automatic access token refresh using a stored refresh token.
No interactive browser flow — that's handled by the setup script.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import anyio
import httpx

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_BUFFER_SECONDS = 60


@dataclass
class ClayOAuthAuth(httpx.Auth):
    """httpx.Auth that refreshes Clay OAuth tokens automatically."""

    client_id: str
    client_secret: str
    refresh_token: str
    token_endpoint: str = "https://api.clay.com/oauth/token"

    _access_token: str | None = None
    _token_expiry: float = 0.0
    _lock: anyio.Lock | None = None

    def _get_lock(self) -> anyio.Lock:
        if self._lock is None:
            self._lock = anyio.Lock()
        return self._lock

    def _is_token_valid(self) -> bool:
        return bool(
            self._access_token
            and time.time() < (self._token_expiry - TOKEN_EXPIRY_BUFFER_SECONDS)
        )

    async def _refresh_access_token(self) -> None:
        """Exchange the refresh token for a new access token."""
        logger.info("Refreshing Clay OAuth access token")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )

        if response.status_code != 200:
            logger.error(
                "Clay OAuth token refresh failed: status=%d body=%s",
                response.status_code,
                response.text[:500],
            )
            raise RuntimeError(
                f"Clay OAuth token refresh failed ({response.status_code}). "
                "The refresh token may have expired — re-run scripts/clay_oauth_setup.py"
            )

        token_data = response.json()
        self._access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        self._token_expiry = time.time() + expires_in

        # Update refresh token if Clay issued a new one
        new_refresh = token_data.get("refresh_token")
        if new_refresh:
            self.refresh_token = new_refresh
            logger.info("Clay issued a new refresh token — update CLAY_OAUTH_REFRESH_TOKEN in Railway")

        logger.info("Clay OAuth access token refreshed, expires in %ds", expires_in)

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Add OAuth Bearer token to requests, refreshing if needed."""
        async with self._get_lock():
            if not self._is_token_valid():
                await self._refresh_access_token()

        request.headers["Authorization"] = f"Bearer {self._access_token}"
        response = yield request

        # If we get a 401, try one refresh and retry
        if response.status_code == 401:
            logger.warning("Clay returned 401, attempting token refresh")
            async with self._get_lock():
                await self._refresh_access_token()
            request.headers["Authorization"] = f"Bearer {self._access_token}"
            yield request
