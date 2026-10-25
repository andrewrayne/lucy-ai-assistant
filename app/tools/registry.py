"""One tool registry for the whole assistant.

Every tool is defined once here and exposed to the Gemini text agent
(and later to Gemini Live sessions and Jarvis).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from google.genai import types

log = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[Any]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments
    handler: Handler
    available: Callable[[], bool] | None = None  # e.g. only when an optional service is configured

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self.parameters,
        )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self, name: str, description: str, parameters: dict | None = None, available: Callable[[], bool] | None = None
    ):
        """Decorator: @registry.register("name", "what it does", {...json schema...}).
        available: shown to the model only while it returns True."""

        def wrap(handler: Handler) -> Handler:
            self._tools[name] = Tool(
                name=name,
                description=description,
                parameters=parameters or {"type": "object", "properties": {}},
                handler=handler,
                available=available,
            )
            return handler

        return wrap

    def names(self) -> list[str]:
        return list(self._tools)

    def gemini_tools(self) -> list[types.Tool]:
        tools = [t for t in self._tools.values() if t.available is None or t.available()]
        if not tools:
            return []
        return [types.Tool(function_declarations=[t.declaration() for t in tools])]

    async def call(self, name: str, args: dict | None) -> dict:
        """Run a tool and always return a dict, so the model sees errors instead of crashing."""
        from app import security

        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}
        blocked = await security.check(name, args)
        if blocked:
            return {"error": blocked}
        try:
            result = await tool.handler(**(args or {}))
        except Exception as exc:  # report the failure back to the model
            log.exception("Tool %s failed", name)
            return {"error": f"{type(exc).__name__}: {exc}"}
        security.note_result(name)
        return result if isinstance(result, dict) else {"result": result}


registry = ToolRegistry()
