"""Внешние ссылки в HTML композиции: всё, что браузер рендера пошёл бы качать.

Одна реализация на проверку CI (scripts/montage_ci_check.py) и на проверку
ссылок черновика (media_sync, задача 8 плана). Ловит:
- атрибуты `src`, `href`, `poster` — в двойных, одинарных кавычках и без них;
- `srcset` в любых кавычках и без них — каждый кандидат, без дескриптора `1x`/`480w`;
- CSS `url(…)` в любом виде — и отдельно, и внутри `@import url(…)`,
  `image-set(url(…) 1x)`, `-webkit-image-set(url(…))`;
- строки `@import "…"` и `image-set("…" 1x)` без `url()`.
Внешняя — со схемой (`https:`, `http:`, `file:` и любой другой, кроме `data:`)
или протокол-относительная (`//cdn…`). Локальные пути, в том числе
`C:/…` Windows (однобуквенной схемы у настоящих URL не бывает), и `data:` — нет.
Порядок — как в документе. Лишнее совпадение безопаснее пропуска: список
служит запретом на сеть, а не картой ресурсов.
"""

from __future__ import annotations

import re

_VALUE = r"""(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<uq>{bare}))"""
_ATTR = re.compile(r"(?<![\w])(?P<name>srcset|src|href|poster)\s*=\s*"
                   + _VALUE.format(bare=r"""[^\s"'=<>`]+"""), re.IGNORECASE)
_CSS_URL = re.compile(r"(?<![\w-])url\(\s*" + _VALUE.format(bare=r"""[^\s"')]+"""), re.IGNORECASE)
_IMPORT = re.compile(r"""@import\s+(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)')""", re.IGNORECASE)
_IMAGE_SET = re.compile(r"image-set\(", re.IGNORECASE)
_STRING = re.compile(r""""(?P<dq>[^"]*)"|'(?P<sq>[^']*)'""")
_URL_CALL = re.compile(r"url\([^)]*\)", re.IGNORECASE)
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]+:|[/\\]{2})", re.IGNORECASE)


def _value(match) -> str:
    groups = match.groupdict()
    for key in ("dq", "sq", "uq"):
        if groups.get(key) is not None:
            return groups[key].strip()
    return ""


def is_external(url: str) -> bool:
    return bool(_EXTERNAL.match(url)) and not url.lower().startswith("data:")


def _srcset(value: str) -> list[str]:
    candidates = (part.strip().split() for part in value.split(","))
    return [words[0] for words in candidates if words]


def _image_set_args(text: str, start: int) -> str:
    """Аргументы `image-set(` до парной скобки; вложенные `url(…)` уже поймал
    _CSS_URL — заменяем их пробелами той же длины, чтобы не задвоить."""

    depth, index, quote = 1, start, ""
    while index < len(text) and depth:
        char = text[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char in "()":
            depth += 1 if char == "(" else -1
        index += 1
    args = text[start:index - 1 if not depth else index]
    return _URL_CALL.sub(lambda m: " " * len(m.group(0)), args)


def external_urls(html: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for match in _ATTR.finditer(html):
        value = _value(match)
        urls = _srcset(value) if match.group("name").lower() == "srcset" else [value]
        found += [(match.start(), url) for url in urls]
    for pattern in (_CSS_URL, _IMPORT):
        found += [(match.start(), _value(match)) for match in pattern.finditer(html)]
    for match in _IMAGE_SET.finditer(html):
        args = _image_set_args(html, match.end())
        found += [(match.end() + string.start(), _value(string)) for string in _STRING.finditer(args)]
    return [url for _position, url in sorted(found, key=lambda pair: pair[0]) if is_external(url)]
