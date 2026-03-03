"""MCP SSE client proxy for Clay MCP gateway."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

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

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the remote MCP server via SSE transport."""
        url = self.config.base_url.rstrip("/")
        # MCP SSE endpoint is typically at /sse
        sse_url = f"{url}/sse" if not url.endswith("/sse") else url

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

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Sync wrapper — call a remote MCP tool via SSE."""
        last_error: Exception | None = None

        for attempt in range(max(1, self.config.retries)):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            try:
                if loop and loop.is_running():
                    # Already inside an async context — run in a new thread
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(asyncio.run, self._call_tool_async(tool_name, arguments))
                        return future.result(timeout=self.config.timeout_seconds + 10)
                else:
                    return asyncio.run(self._call_tool_async(tool_name, arguments))
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
