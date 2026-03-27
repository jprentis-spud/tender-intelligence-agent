import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tender_intelligence_agent.services.clay_oauth import ClayOAuthAuth


def test_token_initially_invalid() -> None:
    auth = ClayOAuthAuth(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
    )
    assert auth._is_token_valid() is False


def test_token_valid_after_set() -> None:
    auth = ClayOAuthAuth(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
    )
    auth._access_token = "tok"
    auth._token_expiry = time.time() + 3600
    assert auth._is_token_valid() is True


def test_token_invalid_when_expired() -> None:
    auth = ClayOAuthAuth(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
    )
    auth._access_token = "tok"
    auth._token_expiry = time.time() - 10
    assert auth._is_token_valid() is False
