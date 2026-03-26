import asyncio

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


def test_normalize_url_from_base_path() -> None:
    client = SculptHackProxyClient(SculptHackProxyConfig(base_url="https://api.clay.com/v3/mcp", api_key="x"))
    assert client._normalize_url(client.config.base_url) == "https://api.clay.com/v3/mcp"


def test_normalize_url_strips_sse_suffix() -> None:
    client = SculptHackProxyClient(SculptHackProxyConfig(base_url="https://api.clay.com/v3/mcp/sse", api_key="x"))
    assert client._normalize_url(client.config.base_url) == "https://api.clay.com/v3/mcp"


def test_normalize_url_strips_trailing_slash() -> None:
    client = SculptHackProxyClient(SculptHackProxyConfig(base_url="https://api.clay.com/v3/mcp/", api_key="x"))
    assert client._normalize_url(client.config.base_url) == "https://api.clay.com/v3/mcp"
