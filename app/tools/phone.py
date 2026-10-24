"""Phone calls: Lucy calls someone on the owner's behalf, or calls the owner."""

from app.config import get_settings
from app.tools.registry import registry


@registry.register(
    "phone_call",
    "Call a phone number on the owner's behalf and do one task by voice: book a table, make or move an appointment, "
    "ask about opening hours or prices. Lucy says she's an AI assistant and that the call is recorded. After the call "
    "the owner gets a summary, the recording, and a calendar event if something was booked. If you don't know the "
    "number, find it first (web_search). Lucy always calls openly, as the owner's AI assistant: she won't call "
    "anonymously or under a made-up pretext; if the owner asks for that, tell them before calling. If nobody "
    "answers or voicemail picks up, the owner is told. Say that you're calling; don't wait for the result.",
    {
        "type": "object",
        "properties": {
            "number": {"type": "string", "description": "Full international number, e.g. +351 21 123 4567."},
            "task": {
                "type": "string",
                "description": "Everything needed for the call: what to do, dates and times, names, number of people, "
                "what alternatives are fine.",
            },
            "person": {"type": "string", "description": "Who is being called, e.g. 'Restaurant Ramiro'."},
            "language": {
                "type": "string",
                "description": "Language to speak on the call, e.g. 'Ukrainian', 'Russian', 'Portuguese'. Only if "
                "the owner asked for one; otherwise leave empty and Lucy speaks the local language of the number "
                "(+351 → European Portuguese, +48 → Polish…).",
            },
        },
        "required": ["number", "task"],
    },
)
async def phone_call(number: str, task: str, person: str = "", language: str = "") -> dict:
    from app.live.phone import place_call  # imported here: app.live imports the tool registry

    return await place_call(number, "task", task=task, person=person, language=language)


@registry.register(
    "call_me",
    "Call the owner's own phone and talk to them (the full assistant, with all tools). Use when the owner asks "
    "'call me', or to tell them something by phone. The call is recorded and the recording sent to Telegram.",
    {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why you're calling, said at the start."},
            "language": {
                "type": "string",
                "description": "Language for the call if the owner asked for one, e.g. 'Ukrainian'. Default English.",
            },
        },
    },
)
async def call_me(reason: str = "", language: str = "") -> dict:
    from app.live.phone import place_call

    number = get_settings().owner_phone_number
    if not number:
        return {"error": "The owner's phone number isn't set (OWNER_PHONE_NUMBER)."}
    return await place_call(number, "owner", task=reason, person="the owner", language=language)
