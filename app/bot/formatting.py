"""Convert the model's Markdown into Telegram HTML.

Telegram's HTML mode is far more forgiving than its MarkdownV2, so we escape
everything and then turn a small set of Markdown patterns back into tags.
"""

import html
import re

TELEGRAM_LIMIT = 4096

_CODE_BLOCK = re.compile(r"```(?:[\w+-]*)\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.M)
_BULLET = re.compile(r"^(\s*)[*-]\s+", re.M)


def markdown_to_html(text: str) -> str:
    # Pull code out first so nothing inside it gets formatted.
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    text = _CODE_BLOCK.sub(lambda m: keep(f"<pre>{html.escape(m.group(1).rstrip(), quote=False)}</pre>"), text)
    text = _INLINE_CODE.sub(lambda m: keep(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text)

    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', text)
    text = _HEADING.sub(r"<b>\1</b>", text)
    text = _BULLET.sub(r"\1• ", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)

    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split long text on paragraph or line breaks so each piece fits in one message."""
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text.strip():
        parts.append(text)
    return parts
