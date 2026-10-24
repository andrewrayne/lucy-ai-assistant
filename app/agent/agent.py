"""Gemini Flash text agent with function calling and streaming."""

import logging
from collections.abc import AsyncIterator

from google.genai import types

from app import costs, gemini, security
from app.agent.prompts import system_prompt
from app.config import get_settings
from app.memory.store import Context
from app.tools import registry

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8


def _config(context: Context | None) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_prompt(context),
        tools=registry.gemini_tools(),
        # We run tools ourselves so the same loop works with streaming.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=get_settings().gemini_thinking_level),
    )


def _history_contents(context: Context | None) -> list[types.Content]:
    if not context:
        return []
    return [
        types.Content(role="model" if m.role == "assistant" else "user", parts=[types.Part(text=m.content)])
        for m in context.history
        if m.role in ("user", "assistant")
    ]


async def stream_reply(
    context: Context | None, user_text: str, parts: list[types.Part] | None = None
) -> AsyncIterator[str]:
    """Yield the reply text piece by piece, running any tools Gemini asks for.

    parts replaces the plain text of the owner's turn (e.g. a voice recording + transcript).
    """
    if costs.over_limit():
        yield costs.limit_message()
        return
    owner_turn = parts or [types.Part(text=user_text)]
    security.start_turn(user_text)  # outside content read during this request can't trigger risky actions
    contents = [*_history_contents(context), types.Content(role="user", parts=owner_turn)]
    config = _config(context)

    for round_number in range(MAX_TOOL_ROUNDS):
        if round_number == MAX_TOOL_ROUNDS - 1:
            # Last round: no more tools, answer with what we have.
            config = config.model_copy(
                update={"tool_config": types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="NONE"))}
            )
        model_parts: list[types.Part] = []
        calls: list[types.FunctionCall] = []

        async for chunk in gemini.stream(contents, config):
            candidate = chunk.candidates[0] if chunk.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                # Keep every part as-is: Gemini needs its thought signatures back.
                model_parts.append(part)
                if part.function_call:
                    calls.append(part.function_call)
                elif part.text and not part.thought:
                    yield part.text

        if not calls:
            return

        # Gemini asked for tools: run them and send the results back.
        contents.append(types.Content(role="model", parts=model_parts))
        results = []
        for call in calls:
            log.info("Tool call: %s(%s)", call.name, call.args)
            result = await registry.call(call.name, call.args)
            results.append(
                types.Part(
                    function_response=types.FunctionResponse(id=call.id, name=call.name, response=result)
                )
            )
        contents.append(types.Content(role="user", parts=results))

    yield "\n\n(I stopped after too many tool calls in a row.)"
