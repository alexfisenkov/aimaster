"""Plain-text primitives shared by the Telegram section renderers.

Pure and offline: no project data, no Bot API, no I/O.  The one thing this
module knows about Telegram is its 4096 UTF-16 unit message limit, counted
here exactly the way ``scripts/creator_studio_bot.py`` splits an outgoing
message, so a section built against this budget never produces a chunk the
transport would have to cut differently.
"""

from __future__ import annotations


TELEGRAM_TEXT_LIMIT = 4096
# One section answers a single button press: three messages is already a
# long scroll on a phone, and the tail line points at the dashboard for
# whatever did not fit.
MAX_SECTION_MESSAGES = 3
SECTION_BUDGET = TELEGRAM_TEXT_LIMIT * MAX_SECTION_MESSAGES


def utf16_length(text: str) -> int:
    """Count a string the way the Bot API counts a message's length."""

    return sum(2 if ord(character) > 0xFFFF else 1 for character in text)


def clip(value, limit: int, *, collapse: bool = True) -> str:
    """Bound one user-authored fragment, collapsing its whitespace by default."""

    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()) if collapse else value.strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)].rstrip() + "…"


def plural(count: int, one: str, few: str, many: str) -> str:
    """Russian numeric agreement for a counted noun."""

    if 11 <= count % 100 <= 14:
        return many
    remainder = count % 10
    if remainder == 1:
        return one
    if 2 <= remainder <= 4:
        return few
    return many


def seconds_label(duration_ms) -> str:
    """Render a scene duration in whole seconds, or nothing when absent."""

    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        return ""
    if duration_ms <= 0:
        return ""
    seconds = duration_ms / 1000
    rendered = f"{seconds:.0f}" if float(seconds).is_integer() else f"{seconds:.1f}"
    return f"{rendered} с"


def assemble(header, blocks, *, footer=(), tail=None, budget: int = SECTION_BUDGET) -> str:
    """Join a header, indivisible blocks and a footer inside one budget.

    ``header`` and ``footer`` are always kept: the footer's room is reserved
    before the first block is admitted.  ``blocks`` are whole units -- a
    block is taken completely or not at all, so a scene never appears with
    half of its lines.  ``tail`` is called with the number of dropped
    blocks and returns the line that says where the rest lives.
    """

    lines = [line for line in header if line is not None]
    footer_lines = [line for line in footer if line is not None]
    reserved = utf16_length("\n".join(footer_lines)) + (1 if footer_lines else 0)
    if tail is not None and blocks:
        reserved += utf16_length("\n" + tail(len(blocks)))
    used = utf16_length("\n".join(lines))
    kept = 0
    for block in blocks:
        chunk = "\n" + "\n".join(line for line in block if line is not None)
        if used + utf16_length(chunk) + reserved > budget:
            break
        lines.extend(line for line in block if line is not None)
        used += utf16_length(chunk)
        kept += 1
    dropped = len(blocks) - kept
    if dropped and tail is not None:
        lines.append(tail(dropped))
    lines.extend(footer_lines)
    return "\n".join(lines)
