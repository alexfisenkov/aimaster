"""План черновика → index.html композиции HyperFrames.

Без внешних ссылок. Таймлайн main на паузе длиной во весь ролик на локальном
GSAP из движка (vendor.py): у композиции без таймлайна (data-no-timeline)
Studio 0.8.75 после правки берёт плеер с длиной 0 и переходит на
воспроизведение перемоткой, которое, по её же предупреждению, звук не
запускает — «Audio will not play in preview» (проба задачи 10b). Анимаций в
таймлайне нет: переход между клипами — CSS-анимация проявления, рантайм
перематывает её покадрово и при таймлайне (рендер с ним и без него совпал
покадрово, проба 10b). Титров в черновике нет; стиль .am-title — для титров,
которые добавит montage edit. Шрифт — только локальный typeface.FONT_FAMILY:
общий sans-serif HyperFrames подменяет на Inter с Google Fonts.
"""

from __future__ import annotations

import html
from typing import Mapping, Sequence

from . import TRACK_OF_LAYER
from .canvas import Canvas
from .draft_plan import TRANSITION, ClipPlan, DraftPlan
from .html_doc import fmt_number as fmt
from .typeface import FONT_STACK, font_face_css

COMPOSITION_ID = "main"
# Длина таймлайна читается с корня при загрузке, а не вписана числом: правка
# длины ролика в Studio или CLI не оставит таймлайн короче ролика. Реестр
# __timelines создаёт рантайм; «|| {}» — чтобы файл не падал и вне него.
TIMELINE_SCRIPT = """<script>
  window.__timelines = window.__timelines || {};
  (function () {
    var root = document.querySelector('[data-composition-id="__ID__"]');
    var tl = gsap.timeline({ paused: true });
    tl.to({}, { duration: parseFloat(root.getAttribute("data-duration")) || 0 });
    window.__timelines["__ID__"] = tl;
  })();
</script>""".replace("__ID__", COMPOSITION_ID)

_STYLE = """      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: #000; font-family: {font_stack}; }}
      #root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden; background: #000; }}
      .am-video {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 1; }}
      .am-fade-in {{ animation: am-fade-in {t}s linear both; }}
      @keyframes am-fade-in {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
      .am-title {{ position: absolute; left: {pad}px; right: {pad}px; bottom: {bottom}px; z-index: 5;
        display: flex; justify-content: center; text-align: center; font-family: {font_stack}; }}
      .am-title span {{ background: rgba(0, 0, 0, 0.6); color: #fff; font-size: {font}px;
        font-weight: 700; line-height: 1.25; padding: {vpad}px {hpad}px; border-radius: {radius}px; }}"""


def _attrs(pairs) -> str:
    parts = []
    for name, value in pairs:
        if value is None or value is False:
            continue
        parts.append(name if value is True else f'{name}="{html.escape(str(value), quote=True)}"')
    return " ".join(parts)


def _common(clip: ClipPlan, layer: str) -> list:
    return [("data-start", fmt(clip.start)), ("data-duration", fmt(clip.duration)),
            ("data-track-index", TRACK_OF_LAYER[layer]), ("data-am-layer", layer),
            ("data-am-scene", clip.scene_id), ("data-am-asset", clip.asset_id)]


def _sound(clip: ClipPlan) -> list:
    return [("data-volume", fmt(clip.volume if clip.volume is not None else 1)),
            ("data-fade-in", fmt(clip.fade_in) if clip.fade_in else None),
            ("data-fade-out", fmt(clip.fade_out) if clip.fade_out else None)]


def _element(clip: ClipPlan, sources: Mapping[str, str]) -> str:
    media = [("src", sources[clip.asset_id]), ("data-media-start", fmt(clip.media_start))]
    if clip.layer == "video":
        classes = "am-video am-fade-in" if clip.visual_fade else "am-video"
        pairs = [("id", clip.clip_id), ("class", classes)] + media + _common(clip, "video")
        pairs += ([("data-has-audio", "true")] + _sound(clip)) if clip.has_audio else [("muted", True)]
        return f"<video {_attrs(pairs + [('playsinline', True)])}></video>"
    pairs = [("id", clip.clip_id)] + media + _common(clip, clip.layer) + _sound(clip)
    return f"<audio {_attrs(pairs)}></audio>"


def title_fragment(clip_id: str, text: str, start: float, duration: float) -> str:
    """Титр на дорожке «Титры» со стилем .am-title. Черновик титров не создаёт:
    их добавляет montage edit (title-add) — по просьбе или в автопилоте по смыслу."""

    pairs = [("id", clip_id), ("class", "clip am-title"), ("data-start", fmt(start)),
             ("data-duration", fmt(duration)), ("data-track-index", TRACK_OF_LAYER["titles"]),
             ("data-am-layer", "titles")]
    return f"<div {_attrs(pairs)}><span>{html.escape(text, quote=False)}</span></div>"


def script_tag(src: str) -> str:
    return f'<script src="{html.escape(src, quote=True)}"></script>'


def render_draft_html(plan: DraftPlan, canvas: Canvas, sources: Mapping[str, str],
                      scripts: Sequence[str]) -> str:
    """`scripts` — локальные ссылки GSAP из `vendor.copy_gsap` (в <head>);
    таймлайн — после корня: скрипт ищет корень и читает его data-duration."""

    scale = canvas.width / 1080
    style = _STYLE.format(w=canvas.width, h=canvas.height, t=fmt(TRANSITION), font_stack=FONT_STACK,
                          pad=round(60 * scale), bottom=round(canvas.height * 0.12),
                          font=max(24, round(64 * scale)), vpad=round(16 * scale),
                          hpad=round(32 * scale), radius=round(16 * scale))
    root = _attrs([("id", "root"), ("data-composition-id", COMPOSITION_ID), ("data-start", "0"),
                   ("data-duration", fmt(plan.duration)), ("data-width", canvas.width),
                   ("data-height", canvas.height),
                   # Слепок структуры проекта на момент сборки: stale_clips
                   # (stale.py) сравнивает его с текущим проектом, чтобы
                   # отличить добавленную/удалённую сцену, смену gen_mode и
                   # новый принятый звуковой слой от сцены/слоя, чей клип
                   # владелец сам убрал со стола.
                   ("data-am-scenes", " ".join(plan.scene_ids)),
                   ("data-am-gen-mode", plan.gen_mode),
                   ("data-am-layers", " ".join(plan.layers))])
    body = ["      " + _element(clip, sources) for clip in plan.clips]
    timeline = ["    " + line for line in TIMELINE_SCRIPT.split("\n")]
    return "\n".join([
        "<!doctype html>", '<html lang="ru">', "  <head>", '    <meta charset="UTF-8" />',
        f'    <meta name="viewport" content="width={canvas.width}, height={canvas.height}" />',
        "    <style>", font_face_css(), style, "    </style>",
        *("    " + script_tag(src) for src in scripts), "  </head>", "  <body>", f"    <div {root}>",
        *body, "    </div>", *timeline, "  </body>", "</html>", ""])
