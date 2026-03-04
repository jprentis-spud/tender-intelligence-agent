"""MCP proxy client for Clay/Sculpt tool gateway."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from tender_intelligence_agent.services.async_bridge import run_coro

from tender_intelligence_agent.services.async_bridge import run_coro

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SculptHackProxyConfig:
    base_url: str
    api_key: str
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout_seconds: float = 30.0
    retries: int = 2


class SculptHackProxyClient:
    """Connects to Clay MCP gateway using SSE or streamable HTTP transport."""

    def __init__(self, config: SculptHackProxyConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        token_value = f"{self.config.auth_scheme} {self.config.api_key}".strip()
        return {
            self.config.auth_header: token_value,
        }

    @staticmethod
    def _candidate_endpoints(base_url: str) -> list[tuple[str, str]]:
        """Return transport/url candidates in best-effort priority order."""
        url = base_url.rstrip("/")
        if url.endswith("/sse"):
            streamable = url.removesuffix("/sse")
            return [("sse", url), ("streamable_http", streamable)]
        return [("sse", f"{url}/sse"), ("streamable_http", url)]

    @staticmethod
    def _extract_result_payload(result: Any, tool_name: str) -> dict[str, Any]:
        if result.isError:
            error_text = " ".join(getattr(c, "text", str(c)) for c in result.content)
            raise RuntimeError(f"Clay MCP tool '{tool_name}' returned error: {error_text}")

        if result.structuredContent and isinstance(result.structuredContent, dict):
            return result.structuredContent

        for content_block in result.content:
            text = getattr(content_block, "text", None)
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    continue

        texts = [getattr(c, "text", str(c)) for c in result.content]
        return {"raw_content": texts, "tool": tool_name}

    async def _call_tool_once_async(
        self,
        transport: str,
        endpoint_url: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        logger.info("Connecting to Clay MCP via %s at %s", transport, endpoint_url)

        if transport == "sse":
            async with sse_client(
                url=endpoint_url,
                headers=self._headers,
                timeout=self.config.timeout_seconds,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    logger.info("Calling tool '%s' with args: %s", tool_name, list(arguments.keys()))
                    result = await session.call_tool(tool_name, arguments)
                    return self._extract_result_payload(result, tool_name)

        if transport == "streamable_http":
            async with streamablehttp_client(
                url=endpoint_url,
                headers=self._headers,
                timeout=self.config.timeout_seconds,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    logger.info("Calling tool '%s' with args: %s", tool_name, list(arguments.keys()))
                    result = await session.call_tool(tool_name, arguments)
                    return self._extract_result_payload(result, tool_name)

        raise RuntimeError(f"Unsupported MCP transport: {transport}")

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the remote MCP server via available transports."""
        last_error: Exception | None = None
        for transport, endpoint_url in self._candidate_endpoints(self.config.base_url):
            try:
                return await self._call_tool_once_async(transport, endpoint_url, tool_name, arguments)
            except Exception as exc:
                logger.warning("MCP endpoint attempt failed for %s (%s): %s", endpoint_url, transport, exc)
                last_error = exc

        detail = str(last_error) if last_error else "Unknown MCP endpoint failure"
        raise RuntimeError(f"Unable to connect to Clay MCP endpoint: {detail}")

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the remote MCP server via SSE transport."""
        last_error: Exception | None = None
        for candidate_url in self._candidate_sse_urls(self.config.base_url):
            try:
                return await self._call_tool_once_async(candidate_url, tool_name, arguments)
            except Exception as exc:
                logger.warning("MCP SSE endpoint attempt failed for %s: %s", candidate_url, exc)
                last_error = exc

        detail = str(last_error) if last_error else "Unknown MCP endpoint failure"
        raise RuntimeError(f"Unable to connect to Clay MCP SSE endpoint: {detail}")

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Sync wrapper — call a remote MCP tool."""
        last_error: Exception | None = None

        for attempt in range(max(1, self.config.retries)):
            try:
                return run_coro(
                    lambda: self._call_tool_async(tool_name, arguments),
                    timeout=self.config.timeout_seconds + 10,
                )
            except Exception as exc:
                logger.warning(
                    "MCP call attempt %d/%d for '%s' failed: %s",
                    attempt + 1,
                    self.config.retries,
                    tool_name,
                    exc,
                )
                last_error = exc

        detail = str(last_error) if last_error else "Unknown MCP proxy error"
        raise RuntimeError(f"Clay MCP call failed for tool '{tool_name}': {detail}")
