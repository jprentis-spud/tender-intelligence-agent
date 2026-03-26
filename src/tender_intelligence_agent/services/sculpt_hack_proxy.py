"""MCP Streamable HTTP client proxy for Clay MCP gateway."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

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
    """Connects to Clay MCP gateway via Streamable HTTP transport."""

    def __init__(self, config: SculptHackProxyConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        token_value = f"{self.config.auth_scheme} {self.config.api_key}".strip()
        key_preview = self.config.api_key[:8] + "..." if self.config.api_key else "<empty>"
        logger.info(
            "Clay MCP auth: header=%s, scheme=%s, key_preview=%s",
            self.config.auth_header,
            self.config.auth_scheme,
            key_preview,
        )
        return {
            self.config.auth_header: token_value,
        }

    @staticmethod
    def _normalize_url(base_url: str) -> str:
        """Ensure the URL points to the MCP endpoint without trailing /sse."""
        url = base_url.rstrip("/")
        if url.endswith("/sse"):
            url = url.removesuffix("/sse")
        return url

    async def _call_tool_once_async(self, url: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        logger.info("Connecting to Clay MCP at %s", url)

        # Debug: raw POST to see exact 401 response body from Clay
        import httpx as _httpx
        async with _httpx.AsyncClient() as _dbg:
            _resp = await _dbg.post(
                url,
                headers={**self._headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "tender-intelligence-agent", "version": "1.0.0"}}},
                timeout=10.0,
            )
            logger.error("Clay MCP debug response: status=%d body=%s", _resp.status_code, _resp.text[:500])

        async with streamablehttp_client(
            url=url,
            headers=self._headers,
            timeout=self.config.timeout_seconds,
        ) as (read_stream, write_stream, _):
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
        """Call a tool on the remote MCP server via Streamable HTTP transport."""
        url = self._normalize_url(self.config.base_url)
        try:
            return await self._call_tool_once_async(url, tool_name, arguments)
        except Exception as exc:
            logger.warning("MCP Streamable HTTP endpoint failed for %s: %s", url, exc)
            raise RuntimeError(f"Unable to connect to Clay MCP endpoint: {exc}") from exc

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
