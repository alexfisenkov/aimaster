"""A validated format is an undoable edit of the existing composition."""
from __future__ import annotations

import json
import re

from . import MontageError
from .formats import validate_profile
from .html_doc import element_attrs, fmt_number, set_attr
from .index_io import read_index, write_index

_STYLE = re.compile(r'<style id="am-format-effects">.*?</style>', re.S)


def apply_profile_text(text, profile):
    profile = validate_profile(profile)
    params = profile["params"]
    rules = ["@keyframes am-format-zoom { from { transform:scale(1); } to { transform:scale(" +
             fmt_number(params["zoom"]) + "); } }"]
    videos = sorted(((identity, attrs) for identity, attrs in element_attrs(text).items()
                     if attrs.get("_tag") == "video"), key=lambda item: float(item[1].get("data-start", 0)))
    for index, (identity, attrs) in enumerate(videos):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", identity):
            raise MontageError("у видеоклипа неподдерживаемый id")
        duration = float(attrs.get("data-duration", 0))
        transition = min(params["transition"], duration)
        animation = f"am-format-zoom {fmt_number(duration)}s linear both"
        if index and transition:
            animation += f", am-fade-in {fmt_number(transition)}s linear both"
        rules.append(f"#{identity} {{ animation: {animation}; transform-origin: center; }}")
    for identity, attrs in element_attrs(text).items():
        if attrs.get("data-am-layer") == "music":
            text = set_attr(text, identity, "data-volume", fmt_number(params["music_volume"]))
    text = set_attr(text, "root", "data-am-format", json.dumps(profile, ensure_ascii=False, sort_keys=True))
    block = '<style id="am-format-effects">\n' + "\n".join(rules) + "\n</style>"
    text = _STYLE.sub("", text)
    return text.replace("</head>", block + "\n</head>", 1)


def preset(ctx, request):
    try:
        profile = validate_profile(json.loads(request.text))
    except (TypeError, ValueError) as error:
        raise MontageError("preset требует проверенный профиль generated-clips") from error
    write_index(ctx.paths.index, apply_profile_text(read_index(ctx.paths.index), profile))
    return {"format_id": profile["id"], "effects": profile["params"]}
