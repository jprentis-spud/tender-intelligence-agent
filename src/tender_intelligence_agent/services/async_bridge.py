"""Helpers for calling async functions from sync code safely."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


def run_coro(coro_factory: Callable[[], Awaitable[T]], timeout: float | None = None) -> T:
    """Execute a coroutine from sync code, even if an event loop is active.

    When a loop is already running (common inside MCP/FastAPI runtimes), we
    execute the coroutine inside a dedicated worker thread with its own loop.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: asyncio.run(coro_factory()))
            return future.result(timeout=timeout)

    return asyncio.run(coro_factory())
