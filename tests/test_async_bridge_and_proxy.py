import asyncio

import pytest

from tender_intelligence_agent.services.async_bridge import run_coro
from tender_intelligence_agent.services.sculpt_hack_proxy import SculptHackProxyClient, SculptHackProxyConfig


async def _sample_coro(value: int) -> int:
    await asyncio.sleep(0)
    return value + 1


def test_run_coro_without_running_loop() -> None:
    assert run_coro(lambda: _sample_coro(1)) == 2


def test_run_coro_with_running_loop() -> None:
    async def _runner() -> int:
        return run_coro(lambda: _sample_coro(2))

    assert asyncio.run(_runner()) == 3


def test_config_oauth_configured_true() -> None:
    config = SculptHackProxyConfig(
        base_url="https://api.clay.com/v3/mcp",
        oauth_client_id="id",
        oauth_client_secret="secret",
        oauth_refresh_token="token",
    )
    assert config.oauth_configured is True


def test_config_oauth_configured_false_when_missing() -> None:
    config = SculptHackProxyConfig(
        base_url="https://api.clay.com/v3/mcp",
        api_key="test-key",
    )
    assert config.oauth_configured is False


def test_config_oauth_configured_false_when_partial() -> None:
    config = SculptHackProxyConfig(
        base_url="https://api.clay.com/v3/mcp",
        oauth_client_id="id",
    )
    assert config.oauth_configured is False


def test_rest_fallback_unknown_tool_raises() -> None:
    client = SculptHackProxyClient(
        SculptHackProxyConfig(base_url="https://api.clay.com", api_key="x")
    )
    with pytest.raises(RuntimeError, match="Unknown tool"):
        client.call_tool("nonexistent-tool", {})


def test_rest_fallback_missing_table_id_raises() -> None:
    client = SculptHackProxyClient(
        SculptHackProxyConfig(base_url="https://api.clay.com", api_key="x")
    )
    with pytest.raises(RuntimeError, match="CLAY_COMPANY_TABLE_ID"):
        client.call_tool("find-and-enrich-company", {"companyIdentifier": "test.com"})
