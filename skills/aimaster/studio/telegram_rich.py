"""Plain text of an incoming Telegram message, including Bot API 10.1 rich messages.

Since Bot API 10.1 a ``Message`` may carry ``rich_message`` = ``{blocks, is_rtl}``
instead of ``text``/``entities``.  ``message_text`` returns ``text`` when it is a
string, otherwise the readable text of ``rich_message``; anything else -> ``None``.
Nothing is dropped silently: unknown blocks/elements contribute all nested
``text``/``url`` strings, links keep their URL, mentions become ``@username``.
"""

from __future__ import annotations

_MAX_DEPTH = 12


def _unknown_strings(node, depth=0):
    if depth > _MAX_DEPTH:
        return ""
    if isinstance(node, list):
        return "".join(
            item if isinstance(item, str) else _unknown_strings(item, depth + 1)
            for item in node
        )
    if not isinstance(node, dict):
        return ""
    parts = []
    for key, value in node.items():
        if key == "type":
            continue
        if isinstance(value, str) and key in {"text", "url", "summary", "title"}:
            parts.append(value)
        elif isinstance(value, (dict, list)):
            nested = _unknown_strings(value, depth + 1)
            if nested:
                parts.append(nested)
    return " ".join(parts)


def rich_text(node, depth=0):
    """RichText (string | list | typed object) -> plain string."""
    if depth > _MAX_DEPTH or node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(rich_text(item, depth + 1) for item in node)
    if not isinstance(node, dict):
        return ""
    inner = rich_text(node.get("text"), depth + 1)
    kind = node.get("type")
    if kind == "url":
        url = node.get("url") if isinstance(node.get("url"), str) else ""
        if not url:
            return inner
        return url if not inner or inner == url else f"{inner} ({url})"
    if kind == "mention":
        username = node.get("username")
        if isinstance(username, str) and username:
            return "@" + username.lstrip("@")
        return inner
    if kind in {"bot_command", "email_address", "phone_number", "bank_card_number",
                "hashtag", "cashtag"}:
        return inner or str(node.get(kind) or "")
    if kind == "custom_emoji":
        return str(node.get("alternative_text") or "")
    if kind == "mathematical_expression":
        return str(node.get("expression") or "")
    if kind == "anchor":
        return ""
    if kind == "button":
        return _button(node.get("button"))
    return inner or _unknown_strings(node)


def _button(button):
    if not isinstance(button, dict):
        return ""
    label = rich_text(button.get("text"))
    url = button.get("url") if isinstance(button.get("url"), str) else ""
    if url and label != url:
        return f"{label} ({url})".strip()
    return label or url


def _caption(block):
    cap = block.get("caption")
    if cap is None:
        return ""
    if isinstance(cap, dict) and "text" in cap:
        return " — ".join(x for x in (rich_text(cap.get("text")), rich_text(cap.get("credit"))) if x)
    return rich_text(cap)


def _blocks(blocks, depth=0):
    lines = []
    if not isinstance(blocks, list) or depth > _MAX_DEPTH:
        return lines

    def push(value):
        lines.extend(line.rstrip() for line in str(value).split("\n"))

    for block in blocks:
        if isinstance(block, str):
            push(block)
            continue
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in {"paragraph", "heading", "footer", "thinking", "pre"}:
            push(rich_text(block.get("text")))
        elif kind in {"divider", "anchor"}:
            continue
        elif kind == "mathematical_expression":
            push(block.get("expression") or "")
        elif kind == "list":
            items = block.get("items")
            for item in items if isinstance(items, list) else []:
                item = item if isinstance(item, dict) else {}
                if item.get("has_checkbox"):
                    marker = "✅ " if item.get("is_checked") else "⬜ "
                elif isinstance(item.get("label"), str) and item["label"]:
                    marker = item["label"] + " "
                else:
                    marker = "• "
                sub = _blocks(item.get("blocks"), depth + 1)
                for index, line in enumerate(sub):
                    lines.append(marker + line if index == 0 else "  " + line)
                if not sub:
                    lines.append(marker.rstrip())
        elif kind == "blockquote":
            lines.extend("> " + line for line in _blocks(block.get("blocks"), depth + 1))
            if block.get("credit"):
                push("> — " + rich_text(block["credit"]))
        elif kind in {"expandable_blockquote", "pullquote"}:
            lines.extend("> " + line for line in rich_text(block.get("text")).split("\n"))
            if block.get("credit"):
                push("> — " + rich_text(block["credit"]))
        elif kind == "table":
            if block.get("caption"):
                push(rich_text(block["caption"]))
            rows = block.get("cells")
            for row in rows if isinstance(rows, list) else []:
                cells = [rich_text(cell.get("text")) if isinstance(cell, dict) else ""
                         for cell in (row if isinstance(row, list) else [])]
                lines.append(" | ".join(cells))
        elif kind == "details":
            push(rich_text(block.get("summary")))
            lines.extend(_blocks(block.get("blocks"), depth + 1))
        elif kind in {"collage", "slideshow"}:
            lines.extend(_blocks(block.get("blocks"), depth + 1))
            if _caption(block):
                push(_caption(block))
        elif kind == "buttons":
            buttons = block.get("buttons")
            lines.extend(x for x in (_button(b) for b in (buttons if isinstance(buttons, list) else [])) if x)
        elif kind in {"photo", "video", "animation", "audio", "document", "voice_note", "map"}:
            if _caption(block):
                push(_caption(block))
        else:
            text = _unknown_strings(block)
            if text:
                push(text)
    return lines


def rich_message_text(rich):
    if not isinstance(rich, dict):
        return ""
    return "\n".join(_blocks(rich.get("blocks"))).strip()


def message_text(message):
    """``message.text`` if it is a string, else text of ``rich_message``, else None."""
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if isinstance(text, str):
        return text
    rich = message.get("rich_message")
    if isinstance(rich, dict):
        return rich_message_text(rich)
    return text
