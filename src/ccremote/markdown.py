"""Convert standard Markdown to Telegram-compatible HTML."""

from __future__ import annotations

import re
from html import escape


def md_to_tg_html(text: str) -> str:
    """Convert Markdown text to Telegram HTML.

    Supports: code blocks, inline code, bold, italic, strikethrough,
    links, and headers. Unsupported syntax (tables, images) passes through
    as plain escaped text.
    """
    # Extract code blocks first to protect them from further processing
    code_blocks: list[str] = []

    def _stash_code_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = escape(m.group(2))
        idx = len(code_blocks)
        if lang:
            code_blocks.append(f'<pre><code class="language-{escape(lang)}">{code}</code></pre>')
        else:
            code_blocks.append(f"<pre>{code}</pre>")
        return f"\x00CODEBLOCK{idx}\x00"

    text = re.sub(r"```(\w*)\n(.*?)```", _stash_code_block, text, flags=re.DOTALL)

    # Extract inline code
    inline_codes: list[str] = []

    def _stash_inline(m: re.Match) -> str:
        idx = len(inline_codes)
        inline_codes.append(f"<code>{escape(m.group(1))}</code>")
        return f"\x00INLINE{idx}\x00"

    text = re.sub(r"`([^`\n]+)`", _stash_inline, text)

    # Now escape HTML in remaining text
    text = escape(text)

    # Headers → bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_ (but not inside words with underscores)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Restore code blocks and inline code
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{idx}\x00", block)
    for idx, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{idx}\x00", code)

    return text
