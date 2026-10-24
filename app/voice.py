"""Voice notes: Gemini hears the audio directly.

The original recording goes to the agent together with a transcript, so the
model always hears everything the owner said even if the transcript misses a
part. The transcript is what gets stored in memory. Replies are text: spoken
conversation happens in calls (Gemini Live), not in Telegram messages.
"""

from google.genai import types

from app.gemini import generate_text

TRANSCRIBE = (
    "Transcribe this voice message word for word, from the very beginning to the very end. "
    "Keep going after pauses, background noise or a change of language: never stop after the first phrase. "
    "Write each part in the language it is spoken in. If a word is unclear, write your best guess. "
    "Output only the transcript, with no quotes or comments."
)


async def transcribe(audio: bytes, mime_type: str = "audio/ogg") -> str:
    return (await generate_text([types.Part.from_bytes(data=audio, mime_type=mime_type), TRANSCRIBE])).strip()


def voice_parts(audio: bytes, mime_type: str, transcript: str) -> list[types.Part]:
    """The owner's turn for the agent: the recording itself plus a helper transcript."""
    return [
        types.Part.from_bytes(data=audio, mime_type=mime_type),
        types.Part(
            text="(The owner sent this voice message. Listen to all of it. "
            f"Automatic transcript, which may be incomplete: {transcript or '(empty)'})"
        ),
    ]
