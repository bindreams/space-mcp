"""Tests for MCP base class and @mcptool decorator."""

from __future__ import annotations

import inspect

import pytest

from space.mcp.base import MCP, mcptool

# Test fixtures ========================================================================================================


class EchoMCP(MCP):

    @mcptool(name="echo", title="Echo Tool")
    async def echo(self, message: str) -> str:
        """Echo the message back."""
        return message

    @mcptool(name="greet", title="Greet Tool")
    async def greet(self, name: str, greeting: str = "Hello") -> str:
        """Greet someone."""
        return f"{greeting}, {name}!"


class FailingMCP(MCP):

    @mcptool(name="fail", title="Fail Tool")
    async def fail(self) -> str:
        """Always fails."""
        raise RuntimeError("something went wrong")


class CustomErrorMCP(MCP):

    @mcptool(name="fail", title="Fail Tool")
    async def fail(self) -> str:
        """Always fails."""
        raise ValueError("bad value")

    def format_error(self, exc: Exception) -> str:
        if isinstance(exc, ValueError):
            return f"Custom: {exc}"
        return super().format_error(exc)


class ChildMCP(EchoMCP):
    """Subclass that adds tools on top of parent tools."""

    @mcptool(name="child_only", title="Child Only Tool")
    async def child_only(self) -> str:
        """Child-specific tool."""
        return "child"


# @mcptool decorator ===================================================================================================


class TestMCPToolDecorator:

    def test_mcptool_on_non_mcp_class_raises(self):
        # Python wraps __set_name__ TypeError in a RuntimeError
        with pytest.raises(RuntimeError) as exc_info:

            class Bad:

                @mcptool(name="x", title="X")
                async def x(self) -> str:
                    return ""

        assert isinstance(exc_info.value.__cause__, TypeError)
        assert "MCP subclasses" in str(exc_info.value.__cause__)

    def test_mcptool_registers_tool_metadata(self):
        assert ("echo", {"name": "echo", "title": "Echo Tool"}) in EchoMCP._mcp_tools
        assert ("greet", {"name": "greet", "title": "Greet Tool"}) in EchoMCP._mcp_tools

    def test_method_is_callable_after_decoration(self):
        """The descriptor replaces itself with the raw function."""
        assert callable(EchoMCP.echo)
        assert inspect.iscoroutinefunction(EchoMCP.echo)

    def test_docstring_preserved(self):
        assert EchoMCP.echo.__doc__ == "Echo the message back."


# Tool registration ====================================================================================================


class TestToolRegistration:

    async def test_tools_registered_on_init(self):
        server = EchoMCP("test")
        tool_names = [t.name for t in await server.list_tools()]
        assert "echo" in tool_names
        assert "greet" in tool_names

    async def test_self_excluded_from_tool_schema(self):
        server = EchoMCP("test")
        tools = {t.name: t for t in await server.list_tools()}
        echo_params = tools["echo"].parameters
        assert "self" not in echo_params.get("properties", {})
        assert "message" in echo_params.get("properties", {})

    async def test_optional_params_in_schema(self):
        server = EchoMCP("test")
        tools = {t.name: t for t in await server.list_tools()}
        greet_params = tools["greet"].parameters
        assert "name" in greet_params["properties"]
        assert "greeting" in greet_params["properties"]
        # 'name' is required, 'greeting' has a default
        assert "name" in greet_params.get("required", [])


# Subclass isolation ===================================================================================================


class TestSubclassIsolation:

    def test_subclasses_have_separate_tool_lists(self):
        assert EchoMCP._mcp_tools is not FailingMCP._mcp_tools
        echo_names = {name for name, _ in EchoMCP._mcp_tools}
        fail_names = {name for name, _ in FailingMCP._mcp_tools}
        assert "echo" in echo_names
        assert "echo" not in fail_names
        assert "fail" in fail_names
        assert "fail" not in echo_names


# Error handling =======================================================================================================


class TestErrorHandling:

    async def test_default_error_handling(self):
        server = FailingMCP("test")
        result = await server.fail()
        assert "**Error:**" in result
        assert "something went wrong" in result

    async def test_custom_format_error(self):
        server = CustomErrorMCP("test")
        result = await server.fail()
        assert result == "Custom: bad value"

    async def test_tools_succeed_normally(self):
        server = EchoMCP("test")
        result = await server.echo("hello")
        assert result == "hello"

    async def test_empty_error_message_uses_class_name(self):

        class EmptyErrorMCP(MCP):

            @mcptool(name="fail", title="Fail")
            async def fail(self) -> str:
                raise RuntimeError("")

        server = EmptyErrorMCP("test")
        result = await server.fail()
        assert "RuntimeError" in result


# Inheritance ==========================================================================================================


class TestInheritance:

    async def test_child_inherits_parent_tools(self):
        server = ChildMCP("test")
        tool_names = [t.name for t in await server.list_tools()]
        assert "echo" in tool_names
        assert "greet" in tool_names
        assert "child_only" in tool_names

    async def test_inherited_tools_are_callable(self):
        server = ChildMCP("test")
        assert await server.echo("hi") == "hi"
        assert await server.child_only() == "child"

    def test_child_does_not_pollute_parent(self):
        parent_names = {name for name, _ in EchoMCP._mcp_tools}
        assert "child_only" not in parent_names
