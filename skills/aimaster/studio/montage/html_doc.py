"""Чтение и точечная правка index.html композиции.

Атрибуты — по id элемента, текст титра — в его <span>, вставка — перед
закрывающим тегом корня. Правка меняет только нужный открывающий тег или
текст: остальная разметка (в том числе то, что переписала Studio: data-hf-id,
<!DOCTYPE html>, <meta …>) остаётся байт в байт.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from . import MontageError

ROOT_ID = "root"
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "source", "track", "wbr"})
_START_TAG = re.compile(
    r"<([a-zA-Z][\w:-]*)((?:\s+[^\s=/>]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?)*)\s*(/?)>")
_ATTR = re.compile(r"([^\s=/>]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?")
_SPAN_OPEN = re.compile(r"<span\b[^>]*>", re.I)


def fmt_number(value: float) -> str:
    """Секунды и громкость в атрибутах: до миллисекунд, без лишних нулей."""

    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _attrs(raw: str):
    for match in _ATTR.finditer(raw or ""):
        value = match.group(2)
        if value is not None and value[:1] in "\"'":
            value = value[1:-1]
        yield match.group(1).lower(), (html.unescape(value) if value is not None else None), match.span()


def _find_start(text: str, element_id: str) -> re.Match:
    for match in _START_TAG.finditer(text):
        if any(name == "id" and value == element_id for name, value, _ in _attrs(match.group(2))):
            return match
    raise MontageError(f"в монтаже нет элемента {element_id}")


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: dict[str, dict] = {}
        self.stack: list[tuple[str, str | None]] = []

    def _register(self, tag, attrs):
        data = {name.lower(): (value if value is not None else "") for name, value in attrs}
        element_id = data.get("id")
        if element_id and element_id not in self.elements:
            self.elements[element_id] = {**data, "_tag": tag, "_text": ""}
        return element_id

    def handle_starttag(self, tag, attrs):
        element_id = self._register(tag, attrs)
        if tag not in _VOID:
            self.stack.append((tag, element_id))

    def handle_startendtag(self, tag, attrs):
        self._register(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        for _tag, element_id in reversed(self.stack):
            if element_id:
                self.elements[element_id]["_text"] += data
                return


def element_attrs(text: str) -> dict[str, dict[str, str]]:
    """{id: {атрибут: значение, "_tag": тег, "_text": текст внутри}}."""

    collector = _Collector()
    collector.feed(text)
    collector.close()
    for data in collector.elements.values():
        data["_text"] = " ".join(data["_text"].split())
    return collector.elements


def set_attr(text: str, element_id: str, name: str, value: str | None) -> str:
    """Ставит, меняет или (value=None) убирает атрибут открывающего тега элемента."""

    match = _find_start(text, element_id)
    raw, start = match.group(2) or "", match.start(2)
    for attr_name, _old, (begin, end) in _attrs(raw):
        if attr_name == name.lower():
            if value is None:
                new_raw = raw[:begin].rstrip() + raw[end:]
            else:
                new_raw = raw[:begin] + f'{name}="{html.escape(value, quote=True)}"' + raw[end:]
            return text[:start] + new_raw + text[start + len(raw):]
    if value is None:
        return text
    insert = start + len(raw)
    return text[:insert] + f' {name}="{html.escape(value, quote=True)}"' + text[insert:]


def element_span(text: str, element_id: str) -> tuple[int, int]:
    """(начало, конец) элемента целиком: от «<» открывающего до «>» закрывающего тега."""

    match = _find_start(text, element_id)
    tag = match.group(1).lower()
    if match.group(3) or tag in _VOID:
        return match.start(), match.end()
    pattern = re.compile(rf"<(/?){re.escape(tag)}\b[^>]*?(/?)>", re.I)
    depth = 1
    for token in pattern.finditer(text, match.end()):
        if token.group(2):
            continue
        depth += -1 if token.group(1) else 1
        if depth == 0:
            return match.start(), token.end()
    raise MontageError(f"у элемента {element_id} нет закрывающего тега")


def set_text(text: str, element_id: str, value: str) -> str:
    """Меняет текст титра — содержимое первого <span> внутри элемента."""

    begin, end = element_span(text, element_id)
    opening = _SPAN_OPEN.search(text, begin, end)
    closing = text.find("</span>", opening.end(), end) if opening else -1
    if closing < 0:
        raise MontageError(f"{element_id} — не титр: в нём нет текста в <span>")
    return text[:opening.end()] + html.escape(value, quote=False) + text[closing:]


def insert_before_root_end(text: str, fragment: str, root_id: str = ROOT_ID) -> str:
    _begin, end = element_span(text, root_id)
    close = text.rfind("<", 0, end)
    line_start = text.rfind("\n", 0, close) + 1
    indent = text[line_start:close]
    if indent.strip():
        return text[:close] + fragment + text[close:]
    return text[:line_start] + indent + "  " + fragment + "\n" + text[line_start:]


def root_duration(text: str) -> float:
    return float(element_attrs(text).get(ROOT_ID, {}).get("data-duration") or 0)
