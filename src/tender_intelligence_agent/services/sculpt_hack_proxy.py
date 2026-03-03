"""MCP SSE client proxy for Clay MCP gateway."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

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
    """Connects to Clay MCP gateway via proper MCP SSE protocol."""

    def __init__(self, config: SculptHackProxyConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        token_value = f"{self.config.auth_scheme} {self.config.api_key}".strip()
        return {
            self.config.auth_header: token_value,
        }

    @staticmethod
    def _candidate_sse_urls(base_url: str) -> list[str]:
        url = base_url.rstrip("/")
        if url.endswith("/sse"):
            return [url, url.removesuffix("/sse")]
        return [f"{url}/sse", url]

    async def _call_tool_once_async(self, sse_url: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        logger.info("Connecting to Clay MCP at %s", sse_url)

        async with sse_client(
            url=sse_url,
            headers=self._headers,
            timeout=self.config.timeout_seconds,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                logger.info("Calling tool '%s' with args: %s", tool_name, list(arguments.keys()))
                result = await session.call_tool(tool_name, arguments)

                if result.isError:
                    error_text = " ".join(
                        getattr(c, "text", str(c)) for c in result.content
                    )
                    raise RuntimeError(
                        f"Clay MCP tool '{tool_name}' returned error: {error_text}"
                    )

                # Extract structured content if available
                if result.structuredContent and isinstance(result.structuredContent, dict):
                    return result.structuredContent

                # Fall back to parsing text content as JSON
                for content_block in result.content:
                    text = getattr(content_block, "text", None)
                    if text:
                        try:
                            parsed = json.loads(text)
                            if isinstance(parsed, dict):
                                return parsed
                        except (json.JSONDecodeError, TypeError):
                            continue

                # Return raw text content as a dict
                texts = [getattr(c, "text", str(c)) for c in result.content]
                return {"raw_content": texts, "tool": tool_name}

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
        """Sync wrapper — call a remote MCP tool via SSE."""
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
