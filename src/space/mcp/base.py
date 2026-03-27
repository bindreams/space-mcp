"""MCP base class with declarative tool registration and automatic error handling."""

from __future__ import annotations

import functools
from typing import Any

from mcp.server.fastmcp import FastMCP


class _MCPToolDescriptor:
    """Descriptor that registers a method as an MCP tool via __set_name__."""

    def __init__(self, func: Any, kwargs: dict[str, Any]) -> None:
        self._func = func
        self._kwargs = kwargs

    def __set_name__(self, owner: type, name: str) -> None:
        """Record tool metadata on the owning class and replace descriptor with raw function."""
        if not (isinstance(owner, type) and issubclass(owner, MCP)):
            raise TypeError(f"@mcptool can only be used on MCP subclasses, not {owner.__name__}")
        # Tuple concatenation creates a new tuple on this class, inheriting parent entries via MRO
        owner._mcp_tools = owner._mcp_tools + ((name, self._kwargs), )
        setattr(owner, name, self._func)


def mcptool(**kwargs: Any):
    """Mark a method for MCP tool registration.

    Accepts the same keyword arguments as FastMCP.add_tool (name, title, description, etc.).
    Can only be used on methods of MCP subclasses.
    """

    def decorator(func: Any) -> _MCPToolDescriptor:
        return _MCPToolDescriptor(func, kwargs)

    return decorator


class MCP(FastMCP):
    """FastMCP subclass with declarative @mcptool registration and automatic error handling.

    Subclasses mark methods with @mcptool(...) and they are automatically registered
    as MCP tools in __init__, each wrapped with error handling that calls format_error().
    """

    _mcp_tools: tuple[tuple[str, dict[str, Any]], ...] = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for name, tool_kwargs in type(self)._mcp_tools:
            method = getattr(self, name)
            wrapped = self._with_error_handling(method)
            self.add_tool(wrapped, **tool_kwargs)
            # Shadow the raw method so direct calls also get error handling
            setattr(self, name, wrapped)

    def _with_error_handling(self, func: Any) -> Any:

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                return self.format_error(exc)

        return wrapper

    def format_error(self, exc: Exception) -> str:
        """Format an exception into a user-friendly error message.

        Override in subclasses to handle domain-specific exceptions.
        """
        msg = str(exc) or type(exc).__name__
        return f"**Error:** {msg}"
